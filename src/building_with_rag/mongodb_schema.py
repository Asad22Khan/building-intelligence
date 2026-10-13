"""MongoDB collections, validators, deterministic IDs, indexes and the vector index (Story 2.2).

Four collections, never merged: sources, sections, chunks, embeddings. Vectors live only on
`embeddings`; the Atlas vector index belongs to `embeddings.vector`.
"""

from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

SOURCES = "sources"
SECTIONS = "sections"
CHUNKS = "chunks"
EMBEDDINGS = "embeddings"

# Fixed by docs/architecture.md; every document and query embedding uses these.
EMBEDDING_MODEL = "voyage-3.5"
EMBEDDING_VERSION = "voyage-3.5"
EMBEDDING_DIMENSIONS = 1024

ACCESS_LEVEL = "public"  # classroom corpus; the field stays for later compatibility

CHUNKING_VERSION = "char2048-o256-v1"
CHUNK_SIZE = 2048
CHUNK_OVERLAP = 256
SPLITTER = f"recursive-char(size={CHUNK_SIZE},overlap={CHUNK_OVERLAP})"

VECTOR_INDEX_NAME = "embeddings_vector_index"
VECTOR_PATH = "vector"
FILTER_FIELDS = ("act", "chapter", "status", "access_level")


# ---------------------------------------------------------------- deterministic IDs


def source_id(key: str) -> str:
    return f"source:{key}"


def chunk_id(section_id: str, chunk_index: int) -> str:
    return f"{section_id}#c{chunk_index}"


def embedding_id(chunk: str, model: str = EMBEDDING_MODEL, dimensions: int = EMBEDDING_DIMENSIONS):
    return f"{chunk}@{model}@{dimensions}"


# ---------------------------------------------------------------- validators


def _validator(required: list[str], properties: dict) -> dict:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", *required],
            "properties": properties,
        }
    }


_STR = {"bsonType": "string"}
_INT = {"bsonType": ["int", "long"]}

VALIDATORS: dict[str, dict] = {
    SOURCES: _validator(
        [
            "source_pdf",
            "source_sha256",
            "act",
            "act_label",
            "status",
            "parser",
            "parser_version",
        ],
        {"source_pdf": _STR, "source_sha256": _STR, "act": _STR, "status": _STR},
    ),
    SECTIONS: _validator(
        [
            "section_id",
            "source_id",
            "act",
            "status",
            "chapter",
            "section_number",
            "heading",
            "text",
            "source_pdf",
            "source_sha256",
            "access_level",
        ],
        {"section_id": _STR, "act": _STR, "text": _STR, "access_level": _STR},
    ),
    CHUNKS: _validator(
        [
            "chunk_id",
            "section_id",
            "chunk_index",
            "chunking_version",
            "splitter",
            "text",
            "embedding_input_text",
            "act",
            "chapter",
            "status",
            "access_level",
            "text_sha256",
        ],
        {"chunk_id": _STR, "section_id": _STR, "chunk_index": _INT, "text": _STR},
    ),
    EMBEDDINGS: _validator(
        [
            "embedding_id",
            "chunk_id",
            "embedding_model",
            "embedding_version",
            "dimensions",
            "vector",
            "act",
            "chapter",
            "status",
            "access_level",
            "input_sha256",
        ],
        {
            "chunk_id": _STR,
            "dimensions": _INT,
            "vector": {"bsonType": "array", "items": {"bsonType": ["double", "int", "long"]}},
        },
    ),
}

# (collection, keys, unique)
ORDINARY_INDEXES: list[tuple[str, list[tuple[str, int]], bool]] = [
    (CHUNKS, [("section_id", ASCENDING), ("chunk_index", ASCENDING)], True),
    (CHUNKS, [("section_id", ASCENDING)], False),
    (
        EMBEDDINGS,
        [("chunk_id", ASCENDING), ("embedding_model", ASCENDING), ("dimensions", ASCENDING)],
        True,
    ),
    (SECTIONS, [("act", ASCENDING), ("section_number", ASCENDING)], False),
]


def ensure_collections(db: Database) -> None:
    """Create each collection with its validator, or update the validator if it exists."""
    existing = {c["name"]: c for c in db.list_collections()}
    for name, validator in VALIDATORS.items():
        if name in existing:
            if existing[name].get("options", {}).get("validator") == validator:
                continue  # already current; no privilege needed
            try:
                db.command("collMod", name, validator=validator, validationLevel="moderate")
            except OperationFailure as exc:
                if exc.code not in (13, 8000):
                    raise
                print(
                    f"NOTICE: not allowed to update the validator on '{name}' (needs dbAdmin); "
                    "keeping the one it already has."
                )
        else:
            db.create_collection(name, validator=validator, validationLevel="moderate")


def ensure_ordinary_indexes(db: Database) -> None:
    for collection, keys, unique in ORDINARY_INDEXES:
        db[collection].create_index(keys, unique=unique)  # idempotent for an equal definition


# ---------------------------------------------------------------- vector index


def vector_index_definition() -> dict:
    return {
        "fields": [
            {
                "type": "vector",
                "path": VECTOR_PATH,
                "numDimensions": EMBEDDING_DIMENSIONS,
                "similarity": "cosine",
            },
            *({"type": "filter", "path": f} for f in FILTER_FIELDS),
        ]
    }


def vector_index_model() -> SearchIndexModel:
    return SearchIndexModel(
        definition=vector_index_definition(), name=VECTOR_INDEX_NAME, type="vectorSearch"
    )


def normalize_definition(definition: dict) -> list[tuple]:
    """Order-insensitive, comparable form of a vectorSearch `fields` array."""
    return sorted(tuple(sorted((k, str(v)) for k, v in f.items())) for f in definition["fields"])
