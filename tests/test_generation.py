import json

from building_with_rag import generation
from building_with_rag.contracts import QueryRequest, QueryResult, RetrievedChunk
from building_with_rag.generation import (
    DRAFT_LINE,
    LOW_CONFIDENCE_LINE,
    add_generation,
    assemble_context,
    generate_events,
)
from building_with_rag.settings import Settings


def passage(n: int, size: int = 100) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"ipc:{n}#c0",
        section_id=f"ipc:{n}",
        act="IPC_1860",
        text=("theft punished imprisonment " * 200)[:size],
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


def fake(*replies):
    """Fake streaming provider: one reply per call (the last repeats), sent in small pieces."""
    calls = []

    def provider(url, headers, payload, timeout):
        calls.append(payload)
        reply = replies[min(len(calls), len(replies)) - 1]
        text = reply if isinstance(reply, str) else json.dumps(reply)
        assert payload["stream"] is True
        for k in range(0, len(text), 7):
            yield text[k : k + 7]

    provider.calls = calls
    return provider


GOOD = {
    "outcome": "answered",
    "answer": 'Theft is "punished" (IPC).\nSee E2.',
    "claims": [{"text": "Theft is punished with imprisonment", "evidence": ["E2"]}],
}
BAD_LABEL = {**GOOD, "claims": [{"text": "Theft is punished", "evidence": ["E9"]}]}


def run(provider, retrieved=None):
    events = list(generate_events(request(), retrieved or retrieval(), provider=provider))
    text = "".join(p for k, p in events if k == "text")
    assert events[-1][0] == "result"
    return text, events[-1][1]


def test_context_bounds_and_labels():
    results = [passage(n, 3000) for n in range(1, 7)]
    selected, outcome = assemble_context(results, limit=5)
    assert list(selected) == ["E1", "E2"]  # third whole passage would exceed 8,000 chars
    assert outcome == "truncated"
    assert list(assemble_context(results, limit=1)[0]) == ["E1"]


def test_good_reply_streams_answer_only_and_matches_result(monkeypatch):
    configured(monkeypatch)
    provider = fake(GOOD)
    text, out = run(provider)
    gen = out.generation
    assert len(provider.calls) == 1  # one operation: the stream and the result share it
    assert text.startswith(DRAFT_LINE) and GOOD["answer"] in text
    body = text.split("✔")[0]
    assert "{" not in body and "outcome" not in body and "claims" not in body
    assert "Confidence: high (attempt 1 of 2)" in text and "ipc:2" in text and "[E2]" in text
    assert gen.outcome == "answered" and gen.answer == GOOD["answer"]
    assert gen.confidence == 0.9 and gen.attempts == 1 and gen.issues == []
    assert [c["label"] for c in gen.citations] == ["E2"]
    assert gen.citations[0]["section_id"] == "ipc:2" and gen.citations[0]["act"] == "IPC_1860"
    assert [p.chunk_id for p in gen.supporting_passages] == ["ipc:2#c0"]
    assert out.status == "ok" and len(out.results) == 2


def test_failed_first_attempt_then_retry_passes(monkeypatch):
    configured(monkeypatch)
    provider = fake(BAD_LABEL, GOOD)
    text, out = run(provider)
    gen = out.generation
    assert len(provider.calls) == 2 and text.count(DRAFT_LINE) == 2
    assert "Check failed: E9 is not a supplied passage" in text
    assert "Trying again (attempt 2 of 2)" in text
    assert gen.outcome == "answered" and gen.attempts == 2 and gen.confidence == 0.9
    assert gen.issues == ["Attempt 1: E9 is not a supplied passage (claim 1)."]
    assert "failed these checks" in provider.calls[1]["messages"][1]["content"]


def test_every_attempt_failing_is_a_low_confidence_draft(monkeypatch):
    configured(monkeypatch)
    text, out = run(fake(BAD_LABEL))
    gen = out.generation
    assert LOW_CONFIDENCE_LINE in text
    assert gen.outcome == "malformed" and gen.answer is None
    assert gen.draft_answer == BAD_LABEL["answer"] and gen.confidence == 0.3
    assert len(gen.issues) == 2 and gen.attempts == 2 and gen.low_confidence_reason
    assert gen.citations == [] and gen.supporting_passages == []  # never stripped or repaired


def test_unsupported_claim_fails_the_support_check(monkeypatch):
    configured(monkeypatch)
    claim = {"text": "Zebras migrate across savannah plains", "evidence": ["E1"]}
    gen = run(fake({**GOOD, "claims": [claim]}))[1].generation
    assert gen.outcome == "malformed" and "not supported by E1" in gen.issues[0]


def test_unparseable_reply_has_no_confidence(monkeypatch):
    configured(monkeypatch)
    text, out = run(fake("not json"))
    gen = out.generation
    assert gen.outcome == "malformed" and gen.answer is None and gen.confidence is None
    assert DRAFT_LINE not in text and "not json" not in text  # raw output never streamed


def test_insufficient_evidence_has_no_answer_or_confidence(monkeypatch):
    configured(monkeypatch)
    reply = {"outcome": "insufficient_evidence", "answer": "", "claims": []}
    text, out = run(fake(reply))
    gen = out.generation
    assert gen.outcome == "insufficient_evidence" and gen.answer is None
    assert gen.confidence is None and "do not support an answer" in text


def test_provider_failure_after_text_is_labelled(monkeypatch):
    configured(monkeypatch)

    def broken(url, headers, payload, timeout):
        yield '{"outcome": "answered", "answer": "Theft is'
        raise TimeoutError("secret-url")

    text, out = run(broken)
    gen = out.generation
    assert "UNAVAILABLE — the answer was interrupted: TimeoutError" in text
    assert "secret-url" not in text and "secret-url" not in out.message
    assert gen.outcome == "unavailable" and gen.confidence is None
    assert gen.draft_answer == "Theft is"


def test_provider_failure_before_text_is_unavailable(monkeypatch):
    configured(monkeypatch)

    def boom(*a):
        raise TimeoutError("secret-url")
        yield

    text, out = run(boom)
    assert out.generation.outcome == "unavailable" and "secret-url" not in text


def test_blank_settings_is_unavailable(monkeypatch):
    monkeypatch.setattr(generation, "get_settings", lambda: Settings(_env_file=None))
    provider = fake({})
    gen = add_generation(request(), retrieval(), provider=provider).generation
    assert gen.outcome == "unavailable" and gen.answer is None and not provider.calls


def test_no_results_makes_no_model_call(monkeypatch):
    configured(monkeypatch)
    provider = fake({})
    gen = add_generation(request(), retrieval("no_results", []), provider=provider).generation
    assert gen.outcome == "insufficient_evidence" and gen.context_outcome == "no_evidence"
    assert not provider.calls
