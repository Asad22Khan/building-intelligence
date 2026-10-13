"""Compact Story 3.1 checks. Prints statuses, outcomes, labels, IDs and lengths only.

Run: uv run python -m building_with_rag.verify_generation

Never prints passage text or the assembled prompt.
"""

import sys

from .contracts import QueryRequest, QueryResult
from .patterns import run_pattern
from .settings import get_settings


def ask(question: str) -> QueryResult:
    return run_pattern(
        QueryRequest(question=question, pattern="semantic", limit=5, generate_answer=True)
    )


def show(label: str, r: QueryResult) -> None:
    g = r.generation
    print(
        f"{label}: retrieval={r.status} results={len(r.results)} "
        f"outcome={g.outcome if g else None} context={g.context_outcome if g else None}"
    )
    if g:
        print(f"  answer={g.answer!r} claims={len(g.claims)} trace={g.trace}")
        for c in g.citations:
            print(
                f"  {c['label']} {c['chunk_id']} section={c['section_id']} act={c['act']} "
                f"source={c['source']} page={c['page']}"
            )


def citations_match(r: QueryResult) -> bool:
    g = r.generation
    by_chunk = {p.chunk_id: p for p in r.results}
    ok = True
    for c in g.citations:
        p = by_chunk.get(c["chunk_id"])
        ok = ok and p is not None
        ok = ok and p.section_id == c["section_id"] and p.act == c["act"]
        ok = ok and p.source == c["source"] and p.page == c["page"]
    cited = {c["label"] for c in g.citations}
    claim_labels = {lb for cl in g.claims for lb in cl["evidence"]}
    ok = ok and claim_labels == cited
    ok = ok and [p.chunk_id for p in g.supporting_passages] == [c["chunk_id"] for c in g.citations]
    print(f"  citations resolve against context: {ok} (count={len(g.citations)})")
    return ok


def main() -> int:
    s = get_settings()
    if not (s.mongodb_uri and s.voyage_api_key):
        print("PREREQUISITE: MONGODB_URI and VOYAGE_API_KEY are required.", file=sys.stderr)
        return 1
    answerable = ask("What is the punishment for theft?")
    show("answerable", answerable)
    unsupported = ask("What is the penalty for a GDPR data breach?")
    show("unsupported", unsupported)
    if not (s.generation_api_base_url and s.generation_api_key):
        print("[PENDING] live answer checks need GENERATION_API_BASE_URL and GENERATION_API_KEY")
        return 0
    ok = answerable.generation.outcome == "answered" and citations_match(answerable)
    ok = ok and unsupported.generation.outcome == "insufficient_evidence"
    ok = ok and unsupported.generation.answer is None and bool(unsupported.results)
    print(f"[{'PASS' if ok else 'FAIL'}] generation checks")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
