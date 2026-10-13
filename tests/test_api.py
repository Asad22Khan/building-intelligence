import json

import pytest
from fastapi.testclient import TestClient

from building_with_rag.app import app
from building_with_rag.registry import MODE_MODEL_IDS

client = TestClient(app)
USER_HI = [{"role": "user", "content": "hi"}]


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_query_placeholder():
    r = client.post("/v1/query", json={"question": "What is theft?", "pattern": "semantic"})
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


def test_chat_non_stream():
    r = client.post("/v1/chat/completions", json={"model": "rag-semantic", "messages": USER_HI})
    assert r.status_code == 200
    assert "not implemented" in r.json()["choices"][0]["message"]["content"]


def test_chat_stream_with_pipe_options():
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
    assert "not implemented" in chunks[1]["choices"][0]["delta"]["content"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"model": "nope", "messages": USER_HI}, 404),
        ({"model": "rag-semantic", "messages": []}, 400),
        ({"model": "rag-semantic", "messages": USER_HI, "rag_options": {"bogus": 1}}, 400),
    ],
)
def test_chat_errors_use_openai_envelope(payload, status):
    r = client.post("/v1/chat/completions", json=payload)
    assert r.status_code == status
    assert "message" in r.json()["error"]
