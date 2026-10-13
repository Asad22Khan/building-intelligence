"""Classroom-sized checks for Story 2.2 against the loaded MongoDB database.

Run: uv run python -m building_with_rag.verify_corpus [--section bns:103] [--question "..."]

Checks one section-to-chunk link, one embedding dimension, index readiness, and one real
$vectorSearch with the top result's chunk_id, section_id, heading and score.
"""

import argparse
import sys

import voyageai

from . import mongodb_schema as schema
from .load_corpus import PrerequisiteError, connect
from .settings import get_settings


def check_section_link(db, section_id: str) -> bool:
    section = db[schema.SECTIONS].find_one({"_id": section_id})
    chunks = list(db[schema.CHUNKS].find({"section_id": section_id}).sort("chunk_index", 1))
    indexes = [c["chunk_index"] for c in chunks]
    ok = bool(section) and indexes == list(range(len(chunks))) and len(chunks) > 0
    print(
        f"[{'PASS' if ok else 'FAIL'}] section {section_id}: {len(chunks)} chunks, "
        f"chunk_index {indexes}"
    )
    return ok


def check_embedding(db) -> bool:
    emb = db[schema.EMBEDDINGS].find_one()
    if not emb:
        print("[FAIL] no embeddings stored yet")
        return False
    linked = db[schema.CHUNKS].count_documents({"_id": emb["chunk_id"]}) == 1
    ok = len(emb["vector"]) == schema.EMBEDDING_DIMENSIONS and linked
    print(
        f"[{'PASS' if ok else 'FAIL'}] embedding {emb['_id']}: len(vector)={len(emb['vector'])}, "
        f"chunk exists={linked}"
    )
    return ok


def check_index(db) -> bool:
    found = list(db[schema.EMBEDDINGS].list_search_indexes(schema.VECTOR_INDEX_NAME))
    ok = bool(found) and bool(found[0].get("queryable"))
    status = found[0].get("status") if found else "missing"
    print(
        f"[{'PASS' if ok else 'FAIL'}] index {schema.VECTOR_INDEX_NAME}: "
        f"queryable={ok} status={status}"
    )
    return ok


def sample_query(db, question: str) -> bool:
    key = get_settings().voyage_api_key
    if not key:
        print("[PENDING] sample query: VOYAGE_API_KEY is blank")
        return True
    vector = (
        voyageai.Client(api_key=key, max_retries=0)
        .embed(
            [question],
            model=schema.EMBEDDING_MODEL,
            input_type="query",
            output_dimension=schema.EMBEDDING_DIMENSIONS,
        )
        .embeddings[0]
    )
    hits = list(
        db[schema.EMBEDDINGS].aggregate(
            [
                {
                    "$vectorSearch": {
                        "index": schema.VECTOR_INDEX_NAME,
                        "path": schema.VECTOR_PATH,
                        "queryVector": vector,
                        "numCandidates": 50,
                        "limit": 3,
                    }
                },
                {"$project": {"chunk_id": 1, "score": {"$meta": "vectorSearchScore"}}},
            ]
        )
    )
    if not hits:
        print("[FAIL] sample query returned no results (index may still be building)")
        return False
    top = hits[0]
    chunk = db[schema.CHUNKS].find_one({"_id": top["chunk_id"]})
    section = db[schema.SECTIONS].find_one({"_id": chunk["section_id"]}) if chunk else None
    ok = bool(chunk and section)
    print(f"[{'PASS' if ok else 'FAIL'}] sample query {question!r}, top result:")
    print(f"    chunk_id   = {top['chunk_id']}")
    print(f"    section_id = {chunk['section_id'] if chunk else None}")
    print(f"    heading    = {section['heading'] if section else None}")
    print(f"    score      = {top['score']:.4f}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--section", default="bns:103")
    parser.add_argument("--question", default="punishment for theft")
    args = parser.parse_args()
    try:
        _, db = connect()
    except PrerequisiteError as exc:
        print(f"PREREQUISITE: {exc}", file=sys.stderr)
        return 1
    print(f"Database: {db.name}")
    results = [
        check_section_link(db, args.section),
        check_embedding(db),
        check_index(db),
        sample_query(db, args.question),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
