"""Compact Story 2.3 checks. Prints only counts, statuses, field values and lengths.

Run: uv run python -m building_with_rag.verify_semantic [--question "..."] [--no-query]

Never prints vectors, embeddings, passage text or raw documents.
"""

import argparse
import sys

from . import mongodb_schema as schema
from .contracts import QueryRequest, SemanticFilters
from .load_corpus import PrerequisiteError, connect
from .semantic import run_semantic
from .settings import get_settings


def check_data(db) -> bool:
    ok = True
    sources = db[schema.SOURCES].count_documents({})
    sections = db[schema.SECTIONS].count_documents({})
    chunks = db[schema.CHUNKS].count_documents({})
    per_act = {
        a["_id"]: a["n"]
        for a in db[schema.SECTIONS].aggregate([{"$group": {"_id": "$act", "n": {"$sum": 1}}}])
    }
    embeddings = db[schema.EMBEDDINGS].count_documents(
        {
            "embedding_model": schema.EMBEDDING_MODEL,
            "embedding_version": schema.EMBEDDING_VERSION,
            "dimensions": schema.EMBEDDING_DIMENSIONS,
        }
    )
    print(f"sources={sources} sections={sections} per_act={per_act} chunks={chunks}")
    print(f"embeddings(model/version/dims match)={embeddings} expected={chunks}")
    if not chunks or embeddings != chunks:
        print("[FAIL] embeddings do not match chunks; re-run load_corpus (it resumes)")
        ok = False
    sample = db[schema.EMBEDDINGS].find_one({}, {"vector": 1})
    length = len(sample["vector"]) if sample else 0
    print(f"sample vector length={length} expected={schema.EMBEDDING_DIMENSIONS}")
    ok = ok and length == schema.EMBEDDING_DIMENSIONS
    found = list(db[schema.EMBEDDINGS].list_search_indexes(schema.VECTOR_INDEX_NAME))
    queryable = bool(found) and bool(found[0].get("queryable"))
    print(f"index {schema.VECTOR_INDEX_NAME}: exists={bool(found)} queryable={queryable}")
    ok = ok and queryable
    print(f"[{'PASS' if ok else 'FAIL'}] data ready")
    return ok


def _show(label: str, request: QueryRequest):
    result = run_semantic(request)
    print(f"{label}: status={result.status} results={len(result.results)}")
    for r in result.results:
        print(
            f"  {r.chunk_id} section={r.section_id} act={r.act} heading={r.heading!r} "
            f"score={r.score:.4f} source={r.source} page={r.page} text_len={len(r.text)}"
        )
    return result


def check_queries(db, question: str) -> bool:
    ok = True
    res = _show("question", QueryRequest(question=question, pattern="semantic", limit=3))
    ok = ok and res.status == "ok" and 0 < len(res.results) <= 3
    scores = [r.score for r in res.results]
    ordered = scores == sorted(scores, reverse=True)
    print(f"ordering non-increasing={ordered} limit_respected={len(res.results) <= 3}")
    ok = ok and ordered

    bns = _show(
        "filter act=BNS_2023",
        QueryRequest(
            question=question,
            pattern="semantic",
            limit=3,
            filters=SemanticFilters(act=["BNS_2023"]),
        ),
    )
    acts = {r.act for r in bns.results}
    print(f"acts returned={sorted(acts)}")
    ok = ok and acts <= {"BNS_2023"} and bns.status == "ok"

    empty = _show(
        "empty scope (access_level=restricted)",
        QueryRequest(
            question=question,
            pattern="semantic",
            filters=SemanticFilters(act=["IPC_1860"], access_level=["restricted"]),
        ),
    )
    ok = ok and empty.status == "no_results" and not empty.results

    if res.results:
        top = res.results[0]
        chunk = db[schema.CHUNKS].find_one({"_id": top.chunk_id}) or {}
        section = db[schema.SECTIONS].find_one({"_id": top.section_id}) or {}
        checks = {
            "text==chunk.text": top.text == chunk.get("text"),
            "chunk.text in section.text": bool(chunk)
            and chunk.get("text", "") in section.get("text", ""),
            "section_id matches chunk": top.section_id == chunk.get("section_id"),
            "source==section.source_pdf": top.source == section.get("source_pdf"),
            "section.source_sha256 present": bool(section.get("source_sha256")),
        }
        for name, passed in checks.items():
            print(f"  passage check {name}: {passed}")
        ok = ok and all(checks.values())
    print(f"[{'PASS' if ok else 'FAIL'}] queries")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--question", default="What is the punishment for theft?")
    parser.add_argument("--no-query", action="store_true", help="data checks only")
    args = parser.parse_args()
    if not get_settings().voyage_api_key:
        print("PREREQUISITE: VOYAGE_API_KEY is blank.", file=sys.stderr)
        return 1
    try:
        _, db = connect()
    except PrerequisiteError as exc:
        print(f"PREREQUISITE: {exc}", file=sys.stderr)
        return 1
    print(f"Database: {db.name}")
    if not check_data(db):
        return 1
    if args.no_query:
        return 0
    return 0 if check_queries(db, args.question) else 1


if __name__ == "__main__":
    sys.exit(main())
