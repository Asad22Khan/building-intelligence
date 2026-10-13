import json

from building_with_rag import generation
from building_with_rag.contracts import QueryRequest, QueryResult, RetrievedChunk
from building_with_rag.generation import add_generation, assemble_context
from building_with_rag.settings import Settings


def passage(n: int, size: int = 100) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"ipc:{n}#c0",
        section_id=f"ipc:{n}",
        act="IPC_1860",
        text="x" * size,
        heading=f"Heading {n}",
        score=0.9,
        source="IPC_1860_bare_act.pdf",
        page=n,
    )


def request(limit: int = 5) -> QueryRequest:
    return QueryRequest(question="q", pattern="semantic", generate_answer=True, limit=limit)


def retrieval(status="ok", results=None) -> QueryResult:
    return QueryResult(
        pattern="semantic",
        status=status,
        message="m",
        results=[passage(1), passage(2)] if results is None else results,
    )


def configured(monkeypatch):
    settings = Settings(
        _env_file=None, generation_api_base_url="http://proxy/v1", generation_api_key="k"
    )
    monkeypatch.setattr(generation, "get_settings", lambda: settings)


def fake(reply):
    calls = []

    def post(url, headers, payload, timeout):
        calls.append(url)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return 200, {"choices": [{"message": {"content": content}}]}

    post.calls = calls
    return post


def test_context_bounds_and_labels():
    results = [passage(n, 3000) for n in range(1, 7)]
    selected, outcome = assemble_context(results, limit=5)
    assert list(selected) == ["E1", "E2"]  # third whole passage would exceed 8,000 chars
    assert outcome == "truncated"
    assert list(assemble_context(results, limit=1)[0]) == ["E1"]


def test_answered_with_resolved_citations(monkeypatch):
    configured(monkeypatch)
    reply = {
        "outcome": "answered",
        "answer": "Theft is punished (IPC).",
        "claims": [{"text": "c", "evidence": ["E2"]}],
    }
    out = add_generation(request(), retrieval(), post=fake(reply))
    gen = out.generation
    assert gen.outcome == "answered" and gen.answer
    assert [c["label"] for c in gen.citations] == ["E2"]
    assert gen.citations[0]["section_id"] == "ipc:2" and gen.citations[0]["act"] == "IPC_1860"
    assert [p.chunk_id for p in gen.supporting_passages] == ["ipc:2#c0"]
    assert out.status == "ok" and len(out.results) == 2


def test_unknown_label_is_malformed(monkeypatch):
    configured(monkeypatch)
    reply = {"outcome": "answered", "answer": "a", "claims": [{"text": "c", "evidence": ["E9"]}]}
    gen = add_generation(request(), retrieval(), post=fake(reply)).generation
    assert gen.outcome == "malformed" and gen.answer is None and gen.citations == []


def test_unparseable_is_malformed(monkeypatch):
    configured(monkeypatch)
    gen = add_generation(request(), retrieval(), post=fake("not json")).generation
    assert gen.outcome == "malformed" and gen.answer is None


def test_insufficient_evidence_has_no_answer(monkeypatch):
    configured(monkeypatch)
    reply = {"outcome": "insufficient_evidence", "answer": "guess", "claims": []}
    gen = add_generation(request(), retrieval(), post=fake(reply)).generation
    assert gen.outcome == "insufficient_evidence" and gen.answer is None


def test_blank_settings_is_unavailable(monkeypatch):
    monkeypatch.setattr(generation, "get_settings", lambda: Settings(_env_file=None))
    post = fake({})
    gen = add_generation(request(), retrieval(), post=post).generation
    assert gen.outcome == "unavailable" and gen.answer is None and not post.calls


def test_provider_failure_is_unavailable(monkeypatch):
    configured(monkeypatch)

    def boom(*a):
        raise TimeoutError("secret-url")

    out = add_generation(request(), retrieval(), post=boom)
    assert out.generation.outcome == "unavailable" and "secret-url" not in out.message


def test_no_results_makes_no_model_call(monkeypatch):
    configured(monkeypatch)
    post = fake({})
    gen = add_generation(request(), retrieval("no_results", []), post=post).generation
    assert gen.outcome == "insufficient_evidence" and gen.context_outcome == "no_evidence"
    assert not post.calls
