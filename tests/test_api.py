import json

import pytest
from fastapi.testclient import TestClient

from building_with_rag import generation, semantic
from building_with_rag.app import app
from building_with_rag.contracts import QueryResult, RetrievedChunk
from building_with_rag.registry import MODE_MODEL_IDS
from building_with_rag.settings import Settings

client = TestClient(app)
USER_HI = [{"role": "user", "content": "hi"}]
GOOD_REPLY = {
    "outcome": "answered",
    "answer": "Theft is punished.",
    "claims": [{"text": "Theft is punished with imprisonment", "evidence": ["E1"]}],
}


def fake_semantic(monkeypatch):
    """Chat and query run the real generation code on monkeypatched retrieval and provider."""
    passage = RetrievedChunk(
        chunk_id="ipc:1#c0",
        section_id="ipc:1",
        act="IPC_1860",
        text="Theft is punished with imprisonment.",
        heading="Theft",
        source="IPC_1860_bare_act.pdf",
        page=3,
    )
    result = QueryResult(pattern="semantic", status="ok", message="m", results=[passage])
    monkeypatch.setattr(semantic, "run_semantic", lambda request: result)
    settings = Settings(
        _env_file=None, generation_api_base_url="http://proxy/v1", generation_api_key="k"
    )
    monkeypatch.setattr(generation, "get_settings", lambda: settings)
    calls = []

    def provider(url, headers, payload, timeout):
        calls.append(payload)
        yield json.dumps(GOOD_REPLY)

    monkeypatch.setattr(generation, "_http_stream", provider)
    return calls


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_query_placeholder():
    # semantic is real since Story 2.3; hybrid is still a placeholder
    r = client.post("/v1/query", json={"question": "What is theft?", "pattern": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_implemented"
    assert body["message"]
    assert body["results"] == []


def test_query_validation():
    assert client.post("/v1/query", json={"question": "", "pattern": "semantic"}).status_code == 422
    r = client.post("/v1/query", json={"question": "x", "pattern": "semantic", "limit": 99})
    assert r.status_code == 422


def test_models():
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids == list(MODE_MODEL_IDS.values())
    assert len(ids) == 6


def test_chat_non_stream_runs_real_generation(monkeypatch):
    calls = fake_semantic(monkeypatch)
    r = client.post("/v1/chat/completions", json={"model": "rag-semantic", "messages": USER_HI})
    assert r.status_code == 200 and len(calls) == 1
    text = r.json()["choices"][0]["message"]["content"]
    assert "Theft is punished." in text and "Confidence: high" in text and "ipc:1" in text


def test_chat_other_modes_stay_placeholders():
    r = client.post("/v1/chat/completions", json={"model": "rag-hybrid", "messages": USER_HI})
    assert "not implemented" in r.json()["choices"][0]["message"]["content"]


def test_query_uses_the_same_operation_and_generate_false_is_unchanged(monkeypatch):
    calls = fake_semantic(monkeypatch)
    body = {"question": "q", "pattern": "semantic", "generate_answer": True}
    gen = client.post("/v1/query", json=body).json()["generation"]
    assert gen["outcome"] == "answered" and gen["confidence"] == 0.9 and len(calls) == 1
    plain = client.post("/v1/query", json={"question": "q", "pattern": "semantic"}).json()
    assert plain["generation"] is None and len(calls) == 1


def test_chat_stream_with_pipe_options(monkeypatch):
    fake_semantic(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "rag-semantic",
            "stream": True,
            "messages": USER_HI,
            "rag_options": {
                "pattern": "semantic",
                "act": ["BNS"],
                "limit": 5,
                "required_acts": [],
                "chapter": None,
            },
        },
    )
    assert r.status_code == 200
    frames = [ln[6:] for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert frames[-1] == "[DONE]"
    chunks = [json.loads(f) for f in frames[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    streamed = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert streamed.startswith("DRAFT — checking evidence") and "Confidence: high" in streamed
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"model": "nope", "messages": USER_HI}, 404),
        ({"model": "rag-semantic", "messages": []}, 400),
    ],
)
def test_chat_errors_use_openai_envelope(payload, status):
    r = client.post("/v1/chat/completions", json=payload)
    assert r.status_code == status
    assert "message" in r.json()["error"]


def test_chat_ignores_unknown_rag_options(monkeypatch):
    fake_semantic(monkeypatch)
    options = {"pattern": "semantic", "caller_id": "evil", "mode": "x", "act": None}
    r = client.post(
        "/v1/chat/completions",
        json={"model": "rag-semantic", "messages": USER_HI, "rag_options": options},
    )
    assert r.status_code == 200
