"""Load the Story 2.1 corpus into MongoDB Atlas: sources, sections, chunks, embeddings, index.

Run: uv run python -m building_with_rag.load_corpus [--batch-size 8] [--delay 20] [--no-embed]

Safe to repeat: documents are upserted by deterministic _id, existing embeddings are skipped,
and an incompatible vector index is reported, never replaced. Credentials are never printed.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import voyageai
from pymongo import MongoClient, ReplaceOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import OperationFailure, PyMongoError

from . import mongodb_schema as schema
from .chunking import embedding_input, sha256_text, split_text
from .settings import get_settings

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
CORPUS_FILES = ("bns_sections.jsonl", "ipc_sections.jsonl")

READY_TIMEOUT_SECONDS = 300
READY_POLL_SECONDS = 10
RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_SECONDS = 30


class PrerequisiteError(Exception):
    """A prerequisite is missing; the message is shown to the user and the run stops."""


# ---------------------------------------------------------------- connection and capability


def connect(db_name: str | None = None) -> tuple[MongoClient, Database]:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise PrerequisiteError(
            "MONGODB_URI is blank. Copy .env.example to .env and set your Atlas M0 connection "
            "string (and allow your IP in the Atlas access list)."
        )
    client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=15000)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        raise PrerequisiteError(
            f"Cannot reach MongoDB ({type(exc).__name__}). Check MONGODB_URI and that the Atlas "
            "IP access list allows this machine."
        ) from None
    return client, client[db_name or settings.mongodb_db_name]


def check_atlas_capability(client: MongoClient, db: Database) -> str:
    """Probe Atlas Search index management; stop clearly if it is unavailable."""
    hosts = [host for host, _ in client.nodes]
    on_atlas_host = any(h.endswith(".mongodb.net") for h in hosts)
    try:
        list(db[schema.EMBEDDINGS].list_search_indexes())
    except OperationFailure as exc:
        if exc.code == 26:  # collection does not exist yet: the command itself is supported
            pass
        elif exc.code == 13:
            raise PrerequisiteError(
                "Your MongoDB user lacks the privilege to manage Atlas Search indexes. Use a "
                "user with 'readWrite' on the database and Atlas Search index access (for "
                "example 'atlasAdmin' on the classroom cluster)."
            ) from None
        else:
            raise PrerequisiteError(
                "This deployment does not support Atlas Search index management "
                f"(code {exc.code}). Story 2.2 needs MongoDB Atlas with $vectorSearch."
            ) from None
    where = "MongoDB Atlas" if on_atlas_host else "an Atlas-compatible deployment"
    return f"{where}: Atlas Search index management and $vectorSearch available"


# ---------------------------------------------------------------- building documents


def read_corpus() -> list[dict]:
    records: list[dict] = []
    for name in CORPUS_FILES:
        path = PROCESSED / name
        if not path.exists():
            raise PrerequisiteError(f"Missing {path}. Run Story 2.1 ingestion first.")
        with path.open(encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f if line.strip())
    return records


def build_documents(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    sources: dict[str, dict] = {}
    sections: list[dict] = []
    chunks: list[dict] = []
    for rec in records:
        key = rec["section_id"].split(":", 1)[0]
        sid = schema.source_id(key)
        sources.setdefault(
            sid,
            {
                "_id": sid,
                **{
                    k: rec[k]
                    for k in (
                        "source_pdf",
                        "source_sha256",
                        "act",
                        "act_label",
                        "status",
                        "parser",
                        "parser_version",
                        "source_status_version",
                    )
                },
            },
        )
        sections.append(
            {
                "_id": rec["section_id"],
                "source_id": sid,
                "access_level": schema.ACCESS_LEVEL,
                **{
                    k: rec[k]
                    for k in (
                        "section_id",
                        "act",
                        "act_label",
                        "status",
                        "chapter",
                        "chapter_title",
                        "section_number",
                        "heading",
                        "text",
                        "source_pdf",
                        "source_sha256",
                        "page_start",
                        "page_end",
                        "needs_review",
                    )
                },
            }
        )
        for index, text in enumerate(split_text(rec["text"])):
            cid = schema.chunk_id(rec["section_id"], index)
            chunks.append(
                {
                    "_id": cid,
                    "chunk_id": cid,
                    "section_id": rec["section_id"],
                    "chunk_index": index,
                    "chunking_version": schema.CHUNKING_VERSION,
                    "splitter": schema.SPLITTER,
                    "text": text,
                    "embedding_input_text": embedding_input(rec, text),
                    "act": rec["act"],
                    "chapter": rec["chapter"],
                    "status": rec["status"],
                    "access_level": schema.ACCESS_LEVEL,
                    "text_sha256": sha256_text(text),
                }
            )
    return list(sources.values()), sections, chunks


def upsert(coll: Collection, docs: list[dict]) -> tuple[int, int]:
    """Replace-upsert by _id. Returns (inserted, modified); identical documents count as neither."""
    if not docs:
        return 0, 0
    result = coll.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs])
    return result.upserted_count, result.modified_count


# ---------------------------------------------------------------- changed-data handling


def report_and_clean(db: Database, sections: list[dict], chunks: list[dict]) -> None:
    """Make changed data visible and remove stale chunks/embeddings; never mix settings."""
    old_sha = {d["_id"]: d["source_sha256"] for d in db[schema.SOURCES].find()}
    new_sha = {d["source_id"]: d["source_sha256"] for d in sections}
    changed_sources = [s for s, sha in old_sha.items() if s in new_sha and new_sha[s] != sha]
    if changed_sources:
        print(f"NOTICE: source PDF hash changed for {changed_sources}; sections are replaced.")

    other_chunking = db[schema.CHUNKS].count_documents(
        {"chunking_version": {"$ne": schema.CHUNKING_VERSION}}
    )
    if other_chunking:
        print(
            f"NOTICE: {other_chunking} stored chunks were made with a different chunking "
            f"version; replacing them with {schema.CHUNKING_VERSION}."
        )

    new_chunk_ids = {c["_id"] for c in chunks}
    stale_chunks = [
        d["_id"] for d in db[schema.CHUNKS].find({}, {"_id": 1}) if d["_id"] not in new_chunk_ids
    ]
    if stale_chunks:
        db[schema.CHUNKS].delete_many({"_id": {"$in": stale_chunks}})
        print(f"Removed {len(stale_chunks)} stale chunks.")

    other_settings = {
        "$or": [
            {"embedding_model": {"$ne": schema.EMBEDDING_MODEL}},
            {"embedding_version": {"$ne": schema.EMBEDDING_VERSION}},
            {"dimensions": {"$ne": schema.EMBEDDING_DIMENSIONS}},
        ]
    }
    other = db[schema.EMBEDDINGS].count_documents(other_settings)
    if other:
        print(
            f"NOTICE: {other} stored embeddings used a different model/version/dimensions "
            f"than {schema.EMBEDDING_MODEL}/{schema.EMBEDDING_DIMENSIONS}; deleting them. "
            "A different dimension count also needs a different vector index (not altered here)."
        )
        db[schema.EMBEDDINGS].delete_many(other_settings)
    orphaned = db[schema.EMBEDDINGS].delete_many({"chunk_id": {"$nin": list(new_chunk_ids)}})
    if orphaned.deleted_count:
        print(f"Removed {orphaned.deleted_count} embeddings whose chunk no longer exists.")


# ---------------------------------------------------------------- vector index


def ensure_vector_index(db: Database) -> str:
    coll = db[schema.EMBEDDINGS]
    found = list(coll.list_search_indexes(schema.VECTOR_INDEX_NAME))
    wanted = schema.vector_index_definition()
    if not found:
        coll.create_search_index(schema.vector_index_model())
        print(f"Created vector index {schema.VECTOR_INDEX_NAME}.")
    else:
        index = found[0]
        current = index.get("latestDefinition") or index.get("definition") or {}
        if index.get("type") != "vectorSearch" or schema.normalize_definition(
            current
        ) != schema.normalize_definition(wanted):
            raise PrerequisiteError(
                f"Index {schema.VECTOR_INDEX_NAME} exists with a different definition and was "
                f"left untouched.\n  existing: {json.dumps(current)}\n"
                f"  expected: {json.dumps(wanted)}\n"
                "Resolve this in Atlas yourself; this command never drops or replaces an index."
            )
        print(f"Reusing existing vector index {schema.VECTOR_INDEX_NAME}.")
    return wait_for_index(coll)


def wait_for_index(coll: Collection) -> str:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while True:
        found = list(coll.list_search_indexes(schema.VECTOR_INDEX_NAME))
        if found and found[0].get("queryable"):
            return "queryable"
        if time.monotonic() >= deadline:
            return "index not ready yet (not queryable within the wait; re-run later)"
        time.sleep(READY_POLL_SECONDS)


# ---------------------------------------------------------------- embeddings


def embed_batch(client: voyageai.Client, texts: list[str]) -> list[list[float]]:
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            result = client.embed(
                texts,
                model=schema.EMBEDDING_MODEL,
                input_type="document",
                output_dimension=schema.EMBEDDING_DIMENSIONS,
            )
            return result.embeddings
        except voyageai.error.RateLimitError:
            if attempt == RATE_LIMIT_RETRIES:
                raise PrerequisiteError(
                    "Voyage rate limit persisted after retries. Progress is saved; "
                    "re-run the command later to resume."
                ) from None
            wait = RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
            print(f"  rate limited; waiting {wait}s (retry {attempt + 1}/{RATE_LIMIT_RETRIES})")
            time.sleep(wait)
    raise AssertionError("unreachable")


def embed_pending(
    db: Database, chunks: list[dict], batch_size: int, delay: float
) -> tuple[int, int]:
    existing = {
        d["_id"]: d["input_sha256"] for d in db[schema.EMBEDDINGS].find({}, {"input_sha256": 1})
    }
    pending = []
    for chunk in chunks:
        eid = schema.embedding_id(chunk["_id"])
        if existing.get(eid) != sha256_text(chunk["embedding_input_text"]):
            pending.append((eid, chunk))
    skipped = len(chunks) - len(pending)
    if not pending:
        return 0, skipped

    key = get_settings().voyage_api_key
    if not key:
        raise PrerequisiteError(
            f"VOYAGE_API_KEY is blank but {len(pending)} chunks need embeddings. Set it in .env."
        )
    client = voyageai.Client(api_key=key, max_retries=0)
    done = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embed_batch(client, [c["embedding_input_text"] for _, c in batch])
        docs = []
        for (eid, chunk), vector in zip(batch, vectors, strict=True):
            if len(vector) != schema.EMBEDDING_DIMENSIONS:
                raise PrerequisiteError(
                    f"Voyage returned {len(vector)} dimensions for {chunk['_id']}; "
                    f"expected {schema.EMBEDDING_DIMENSIONS}. Nothing stored for this batch."
                )
            docs.append(
                {
                    "_id": eid,
                    "embedding_id": eid,
                    "chunk_id": chunk["_id"],
                    "embedding_model": schema.EMBEDDING_MODEL,
                    "embedding_version": schema.EMBEDDING_VERSION,
                    "dimensions": schema.EMBEDDING_DIMENSIONS,
                    "vector": vector,
                    "act": chunk["act"],
                    "chapter": chunk["chapter"],
                    "status": chunk["status"],
                    "access_level": chunk["access_level"],
                    "input_sha256": sha256_text(chunk["embedding_input_text"]),
                }
            )
        upsert(db[schema.EMBEDDINGS], docs)
        done += len(batch)
        print(f"embedded {done}/{len(pending)} chunks ({skipped} already present)", flush=True)
        if start + batch_size < len(pending):
            time.sleep(delay)
    return done, skipped


# ---------------------------------------------------------------- main


def run(batch_size: int, delay: float, embed: bool) -> int:
    client, db = connect()
    print(f"Connected. Database: {db.name}")
    print(f"Capability: {check_atlas_capability(client, db)}")

    sources, sections, chunks = build_documents(read_corpus())
    schema.ensure_collections(db)
    report_and_clean(db, sections, chunks)
    for name, docs in (
        (schema.SOURCES, sources),
        (schema.SECTIONS, sections),
        (schema.CHUNKS, chunks),
    ):
        inserted, modified = upsert(db[name], docs)
        print(f"{name}: {len(docs)} documents ({inserted} new, {modified} updated)")
    schema.ensure_ordinary_indexes(db)

    index_status = ensure_vector_index(db)
    created = skipped = 0
    stopped = None
    if embed:
        try:
            created, skipped = embed_pending(db, chunks, batch_size, delay)
        except PrerequisiteError as exc:
            stopped = str(exc)

    print("--- summary ---")
    for name in (schema.SOURCES, schema.SECTIONS, schema.CHUNKS, schema.EMBEDDINGS):
        print(f"{name}: {db[name].count_documents({})}")
    print(f"embeddings created this run: {created}; skipped (already present): {skipped}")
    print(f"vector index {schema.VECTOR_INDEX_NAME}: {index_status}")
    if stopped:
        print(f"STOPPED: {stopped}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=8, help="chunks per Voyage request")
    parser.add_argument("--delay", type=float, default=20.0, help="seconds between requests")
    parser.add_argument("--no-embed", action="store_true", help="load and index, skip embedding")
    args = parser.parse_args()
    try:
        return run(args.batch_size, args.delay, not args.no_embed)
    except PrerequisiteError as exc:
        print(f"PREREQUISITE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
