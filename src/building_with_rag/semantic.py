"""Semantic retrieval (Story 2.3): question -> Voyage query embedding -> $vectorSearch -> passages.

Returns source passages in QueryResult.results only; no answer is generated. A similarity score
ranks passages against each other and is never treated as proof of correctness.
"""

from functools import lru_cache

import voyageai
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from . import mongodb_schema as schema
from .contracts import OmittedCandidate, QueryRequest, QueryResult, RetrievedChunk, SemanticFilters
from .settings import get_settings

CANDIDATE_MULTIPLIER = 10
MIN_CANDIDATES = 50
MAX_CANDIDATES = 200  # well under Atlas's own ceiling

ROOT_ACCESS_LEVELS = [schema.ACCESS_LEVEL]  # the fixed demo caller sees public passages only


class Unavailable(Exception):
    """A service or configuration failure. The message is safe to show to the caller."""


# ---------------------------------------------------------------- pure parts


def effective_filters(filters: SemanticFilters | None) -> dict[str, list[str]]:
    """Caller lists can only narrow the server scope. Empty `access_level` means no match."""
    requested = list(filters.access_level) if filters else []
    access = (
        [a for a in ROOT_ACCESS_LEVELS if a in requested] if requested else list(ROOT_ACCESS_LEVELS)
    )
    return {
        "act": list(filters.act) if filters else [],
        "status": list(filters.status) if filters else [],
        "access_level": access,
    }


def vector_filter(effective: dict[str, list[str]]) -> dict | None:
    """Build the in-database filter. Caller values appear only as strings inside `$in` lists."""
    clauses = [{field: {"$in": values}} for field, values in effective.items() if values]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def num_candidates(limit: int) -> int:
    return min(max(limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES), MAX_CANDIDATES)


def build_pipeline(vector: list[float], limit: int, flt: dict | None) -> list[dict]:
    stage: dict = {
        "index": schema.VECTOR_INDEX_NAME,
        "path": schema.VECTOR_PATH,
        "queryVector": vector,
        "numCandidates": num_candidates(limit),
        "limit": limit,
    }
    if flt:
        stage["filter"] = flt
    return [
        {"$vectorSearch": stage},
        {"$project": {"chunk_id": 1, "score": {"$meta": "vectorSearchScore"}}},
    ]


def _result(request: QueryRequest, status: str, message: str, trace: list[str], **extra):
    return QueryResult(
        pattern=request.pattern, status=status, message=message, trace=trace, **extra
    )


def unavailable_result(request: QueryRequest, message: str, trace: list[str]) -> QueryResult:
    return _result(request, "unavailable", message, [*trace, "outcome=unavailable"])


# ---------------------------------------------------------------- services


@lru_cache
def _client(uri: str) -> MongoClient:
    return MongoClient(uri, serverSelectionTimeoutMS=10000)


def _embed_query(question: str) -> list[float]:
    settings = get_settings()
    try:
        vector = (
            voyageai.Client(api_key=settings.voyage_api_key, max_retries=1, timeout=30)
            .embed(
                [question],
                model=schema.EMBEDDING_MODEL,
                input_type="query",
                output_dimension=schema.EMBEDDING_DIMENSIONS,
            )
            .embeddings[0]
        )
    except Exception as exc:  # provider errors vary; never echo them (they may carry request data)
        raise Unavailable(
            f"The embedding service failed ({type(exc).__name__}). Check VOYAGE_API_KEY and "
            "rate limits, then try again."
        ) from None
    if len(vector) != schema.EMBEDDING_DIMENSIONS:
        raise Unavailable(
            f"The embedding had {len(vector)} dimensions, expected {schema.EMBEDDING_DIMENSIONS}."
        )
    return vector


def _check_index(db) -> None:
    found = list(db[schema.EMBEDDINGS].list_search_indexes(schema.VECTOR_INDEX_NAME))
    if not found:
        raise Unavailable(
            f"The vector index '{schema.VECTOR_INDEX_NAME}' does not exist. "
            "Run the Story 2.2 load command."
        )
    if not found[0].get("queryable"):
        raise Unavailable(
            f"The vector index '{schema.VECTOR_INDEX_NAME}' is not queryable yet. Try again soon."
        )


def _to_chunk(hit: dict, chunk: dict, section: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk["_id"],
        section_id=chunk["section_id"],
        act=chunk["act"],
        text=chunk["text"],
        heading=section.get("heading"),
        score=hit.get("score"),
        source=section.get("source_pdf"),
        page=section.get("page_start"),
        chapter=chunk.get("chapter"),
    )


# ---------------------------------------------------------------- entry point


def run_semantic(request: QueryRequest) -> QueryResult:
    settings = get_settings()
    effective = effective_filters(request.filters)
    limit = request.limit
    candidates = num_candidates(limit)
    trace = [
        f"pattern={request.pattern}",
        f"embedding={schema.EMBEDDING_MODEL}/{schema.EMBEDDING_DIMENSIONS}",
        f"filters={effective}",
        f"limit={limit} numCandidates={candidates}",
    ]

    if not effective["access_level"]:
        trace.append("hits=0 (access_level filter leaves no possible match)")
        return _result(
            request,
            "no_results",
            "No passages are available within the requested access level.",
            trace,
        )
    if not settings.mongodb_uri or not settings.voyage_api_key:
        required = {"MONGODB_URI": settings.mongodb_uri, "VOYAGE_API_KEY": settings.voyage_api_key}
        missing = [name for name, value in required.items() if not value]
        return unavailable_result(
            request, f"Retrieval is not configured: set {', '.join(missing)} in .env.", trace
        )

    try:
        db = _client(settings.mongodb_uri)[settings.mongodb_db_name]
        _check_index(db)
        vector = _embed_query(request.question)
        hits = list(
            db[schema.EMBEDDINGS].aggregate(
                build_pipeline(vector, limit, vector_filter(effective))
            )
        )
        results: list[RetrievedChunk] = []
        omitted: list[OmittedCandidate] = []
        for hit in hits[:limit]:
            chunk = db[schema.CHUNKS].find_one({"_id": hit["chunk_id"]})
            if not chunk:
                omitted.append(
                    OmittedCandidate(chunk_id=hit["chunk_id"], omitted_reason="chunk_not_found")
                )
                continue
            section = db[schema.SECTIONS].find_one({"_id": chunk["section_id"]})
            if not section:
                omitted.append(
                    OmittedCandidate(chunk_id=hit["chunk_id"], omitted_reason="section_not_found")
                )
                continue
            results.append(_to_chunk(hit, chunk, section))
    except Unavailable as exc:
        return unavailable_result(request, str(exc), trace)
    except PyMongoError as exc:
        return unavailable_result(
            request,
            f"MongoDB failed ({type(exc).__name__}). Check MONGODB_URI, the Atlas access list "
            "and the vector index.",
            trace,
        )

    trace.append(f"hits={len(hits)}")
    if omitted:
        trace.append(f"omitted={len(omitted)}")
    if not results:
        return _result(
            request,
            "no_results",
            "The search ran but no passages matched.",
            trace,
            omitted_candidates=omitted,
        )
    return _result(
        request,
        "ok",
        f"Retrieved {len(results)} candidate passage(s) for inspection. Scores rank passages "
        "against each other; they do not show a passage is correct or sufficient to answer.",
        trace,
        results=results,
        omitted_candidates=omitted,
    )
