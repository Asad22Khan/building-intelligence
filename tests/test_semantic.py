import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from building_with_rag import semantic
from building_with_rag.app import app
from building_with_rag.contracts import QueryRequest, SemanticFilters
from building_with_rag.semantic import effective_filters, num_candidates, vector_filter
from building_with_rag.settings import Settings

client = TestClient(app)


@pytest.mark.parametrize(
    "filters",
    [
        {"chapter": ["I"]},
        {"act": {"$ne": "BNS_2023"}},
        {"act": [{"$gt": ""}]},
        {"$where": "1"},
    ],
)
def test_filters_reject_unknown_and_mongo_fragments(filters):
    with pytest.raises(ValidationError):
        SemanticFilters(**filters)
    r = client.post(
        "/v1/query", json={"question": "x", "pattern": "semantic", "filters": filters}
    )
    assert r.status_code == 422


def test_own_list_fields_accepted():
    f = SemanticFilters(act=["BNS_2023"], status=["in_force"], access_level=["public"])
    assert effective_filters(f) == {
        "act": ["BNS_2023"],
        "status": ["in_force"],
        "access_level": ["public"],
    }


def test_access_level_can_only_narrow():
    assert effective_filters(None)["access_level"] == ["public"]
    assert effective_filters(SemanticFilters(access_level=["restricted"]))["access_level"] == []
    both = SemanticFilters(access_level=["public", "restricted"])
    assert effective_filters(both)["access_level"] == ["public"]


def test_vector_filter_shape_and_bounds():
    assert vector_filter({"act": [], "status": [], "access_level": ["public"]}) == {
        "access_level": {"$in": ["public"]}
    }
    assert "$and" in vector_filter({"act": ["IPC_1860"], "status": [], "access_level": ["public"]})
    assert num_candidates(1) == 50 and num_candidates(20) == 200


def test_blank_question_and_limit_rejected():
    blank = {"question": "  ", "pattern": "semantic"}
    assert client.post("/v1/query", json=blank).status_code == 422
    for limit in (0, 21):
        body = {"question": "x", "pattern": "semantic", "limit": limit}
        assert client.post("/v1/query", json=body).status_code == 422


def test_empty_scope_is_no_results_without_services():
    req = QueryRequest(
        question="x", pattern="semantic", filters=SemanticFilters(access_level=["restricted"])
    )
    result = semantic.run_semantic(req)
    assert result.status == "no_results" and result.results == []


def test_blank_credentials_is_unavailable_not_no_results(monkeypatch):
    monkeypatch.setattr(semantic, "get_settings", lambda: Settings(_env_file=None))
    result = semantic.run_semantic(QueryRequest(question="x", pattern="semantic"))
    assert result.status == "unavailable" and result.results == []
    assert "MONGODB_URI" in result.message
