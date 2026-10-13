# Story 2.2: MongoDB, Chunks, Embeddings and Vector Index

## Purpose

Load the Story 2.1 corpus into MongoDB Atlas, split each section into chunks, embed the chunks with Voyage, and create one Atlas vector index. The result is searchable evidence in the same database the rest of the application uses. This story extends Stories 1.1 and 2.1; it does not replace them. Existing routes, modes, model IDs, settings and contracts stay as they are.

Out of scope: retrieval endpoints, answer generation, hybrid or keyword search, re-ranking, any separate vector store, access control, deployment, and broad validation. Semantic retrieval is a later story.

## Prerequisites

- Stories 1.1 and 2.1 are complete: `uv sync` works, `uv run pytest` passes, and `data/processed/bns_sections.jsonl` (358 records) and `data/processed/ipc_sections.jsonl` (550 records) exist.
- Read first: `docs/config.yaml` (absent: no configured project path), `docs/architecture.md`, Stories 1.1 and 2.1, the code under `src/building_with_rag/`, and the two JSONL files. Preserve existing work.
- Settings come from an untracked `.env` (copy of `.env.example`) through the existing `Settings` class. Use exactly these existing variables; do not rename, remove or add any:
  - `MONGODB_URI`: Atlas free-tier (M0) connection string; the Atlas IP access list must allow your machine.
  - `MONGODB_DB_NAME`: the working database (`building_with_rag`).
  - `MONGODB_TEST_DB_NAME`: the database used by tests (`building_with_rag_test`).
  - `VOYAGE_API_KEY`: the Voyage key.
- Never print, log or commit credentials or the connection string. Print the database name only.
- Embedding choice is fixed by `docs/architecture.md`: Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions. Read the values from there; do not substitute another model, version or size.
- **Stop with a clear prerequisite message** (and write nothing) if:
  - `MONGODB_URI` is blank or MongoDB cannot be reached;
  - the deployment is not Atlas, or the user lacks the privilege to manage Atlas Search indexes (see step 3);
  - `VOYAGE_API_KEY` is blank when embedding is needed (loading sections and chunks may still run without it).

## Work to do

### 1. Dependencies

PyMongo is already installed. Add only what is still needed through UV (for example the `voyageai` client: `uv add voyageai`). Settings loading needs nothing new.

### 2. Schema module

Create `src/building_with_rag/mongodb_schema.py` (the package layout from Story 1.1; there is no separate `ingestion/` directory). It is the single place that defines, and that all code in this story reuses:

- collection name constants: `sources`, `sections`, `chunks`, `embeddings`;
- one JSON-Schema validator per collection (applied with `collMod`/`create_collection`, so inserts that miss required fields fail);
- deterministic ID helpers (see below);
- ordinary (non-vector) indexes, created idempotently;
- the vector index name and definition (step 3).

The existing `SectionDocument` and `ChunkDocument` models in `contracts.py` were typed placeholders from Story 1.1. Extend them additively to match the shapes below and leave the old fields in place, but do not store vectors on chunks: `ChunkDocument.embedding` stays unused.

Four collections, never merged:

| Collection | Key fields |
| --- | --- |
| `sources` | `_id` = `source:<key>` (`source:bns`, `source:ipc`), `source_pdf`, `source_sha256`, `act`, `act_label`, `status`, `parser`, `parser_version`, `source_status_version` |
| `sections` | `_id`/`section_id` (the Story 2.1 act-qualified value, for example `bns:103`), `source_id`, `act`, `act_label`, `status`, `chapter`, `chapter_title`, `section_number`, `heading`, `text`, `source_pdf`, `source_sha256`, `page_start`, `page_end`, `needs_review`, `access_level` |
| `chunks` | `_id`/`chunk_id`, `section_id`, `chunk_index`, `chunking_version`, `splitter`, `text`, `embedding_input_text`, `act`, `chapter`, `status`, `access_level`, `text_sha256` |
| `embeddings` | `_id`/`embedding_id`, `chunk_id`, `embedding_model`, `embedding_version`, `dimensions`, `vector`, `act`, `chapter`, `status`, `access_level`, `input_sha256` |

- Use `access_level = "public"` on every section, chunk and embedding. Keep the field so the document shape stays compatible with later access control; do not build any access logic.
- **Deterministic IDs:** `chunk_id = <section_id>#c<chunk_index>` (for example `bns:103#c0`); `embedding_id = <chunk_id>@<embedding_model>@<dimensions>`. The same input always gives the same ID.
- `embeddings` carries only the denormalized `act`, `chapter`, `status` and `access_level` it needs for vector filtering. Section number and source identifiers are **not** copied onto `embeddings`; they stay on `chunks`/`sections` and are applied after `chunk_id` resolution.
- Ordinary indexes (idempotent): unique `chunks.section_id + chunk_index`, `chunks.section_id`, unique `embeddings.chunk_id + embedding_model + dimensions`, `sections.act + section_number`.

### 3. Atlas capability check and vector index

1. Identify the deployment from the connection (hello/`buildInfo`, plus a harmless call to the Atlas Search index API). Record the exact capability found: Atlas with `$vectorSearch` and Atlas Search index management (the M0 free tier is expected to have both).
2. If the deployment is not Atlas, or listing or creating a search index is refused for lack of privilege, **stop** and report that prerequisite. Do not try a generic or legacy index.
3. Create the index on `embeddings` with PyMongo's `create_search_index` and a `SearchIndexModel` of `type="vectorSearch"`, named `embeddings_vector_index`, with a `fields` array:

   ```json
   {
     "fields": [
       {"type": "vector", "path": "vector", "numDimensions": 1024, "similarity": "cosine"},
       {"type": "filter", "path": "act"},
       {"type": "filter", "path": "chapter"},
       {"type": "filter", "path": "status"},
       {"type": "filter", "path": "access_level"}
     ]
   }
   ```

   Do not use the legacy `knnVector`/`mappings` syntax (that belongs to `search`-type indexes). Take `numDimensions` from the fixed architecture choice and the field names from the schema module.
4. **Repeat-safe:** if an index of that name exists with a compatible definition, reuse it. If it exists with a different definition, report the difference and stop; never drop or replace it.
5. Wait for readiness for a bounded time (for example up to 5 minutes, polling every 10 seconds, until `queryable` is true). If it is not ready in time, report "index not ready yet" rather than failing the load.

### 4. Chunking

- Split each section's `text` on its own (never across sections or acts) with a recursive character splitter: target about 2,048 characters (about 512 tokens) with about 256 characters of overlap, preferring paragraph, then line, then sentence, then word boundaries. Sections at or under the target stay as one chunk.
- A small hand-written splitter is enough; add a library only if it removes real code.
- Each chunk records `chunking_version` (for example `char2048-o256-v1`) and `splitter` (the splitter name and parameters).
- `embedding_input_text` is the text actually sent to Voyage: the chunk text prefixed with a short context line built from `act_label`, section number and `heading`. Keep `text` as the plain section text; the prefix only goes into `embedding_input_text`.
- Each chunk keeps its parent `section_id`, `act`, `chapter` and `status`, and the section keeps `source_pdf`, `source_sha256` and the page range from Story 2.1, so every passage traces back to its source.

### 5. Load command

Add a small module run as `uv run python -m building_with_rag.load_corpus` (the name may differ; record it in `docs/architecture.md`). In order:

1. Connectivity and Atlas check (step 3.1). Stop with a clear message on failure.
2. Upsert `sources`, `sections`, then `chunks` from the JSONL files, using the deterministic IDs.
3. Create ordinary indexes and the vector index (wait for readiness).
4. Embed chunks that have no matching embedding (step 6).
5. Print a short summary: counts per collection, embeddings created and skipped, index status.

Use `upsert`/bulk writes keyed by `_id`; never insert blindly.

### 6. Embedding: batched, rate limited, resumable

- A free Voyage key is rate limited. Send small batches (start with 8 chunks per request), wait a fixed delay between requests (start with about 20 seconds, matching a 3-requests-per-minute limit), and on a rate-limit error back off and retry a bounded number of times, then stop with a clear message that a re-run will resume.
- Print progress after every batch (for example `embedded 64/987 chunks`).
- Write each batch's embeddings as soon as it returns, keyed by `embedding_id`. An interrupted run loses at most one batch.
- Skip any chunk whose embedding already exists with the same `input_sha256` (hash of `embedding_input_text`), model, version and dimensions.
- Check every returned vector has the fixed dimension before storing it.
- **Expected run duration:** about 1,000 chunks (about 400 BNS and 600 IPC) at 8 per request and about 20 seconds per request is roughly 40 minutes on the first full run, which matches the note in `docs/architecture.md`. A re-run with nothing changed finishes in seconds and makes no Voyage calls.

### 7. Re-runs and changes

- Unchanged data: re-running adds no duplicate documents and makes no new embeddings.
- Changed section text or a new `source_sha256`: update the section, regenerate its chunks, and embed only chunks whose `text_sha256`/`input_sha256` changed. Remove chunks (and their embeddings) that no longer exist for that section, and print how many.
- Changed `chunking_version`, embedding model, version or dimensions: do not mix silently. Print a visible notice that stored data was made with different settings and name the affected collection. Old-setting chunks and embeddings for the same sections are replaced as one explicit step, not left alongside new ones. A different dimension count is a different vector index definition: report it under step 3.4 rather than altering the existing index.

### 8. Architecture notes

Update `docs/architecture.md` (keep it short) with: the four collections and their roles, the chunking choice and `chunking_version`, the embedding decision (model, version, dimensions, the context prefix), the index name `embeddings_vector_index` and its `vectorSearch` definition, the commands, and these limitations: classroom `access_level` is always `public`; no retrieval endpoint exists yet; later semantic retrieval queries `embeddings`, then resolves each `chunk_id` to its `chunks` and `sections` records before building a `RetrievedChunk`; section number and source identifiers are applied after resolution, not as vector filters.

## Completion checks

Keep these classroom-sized. Run each and record the real result. If a service or credential is unavailable, mark the affected check **pending** and say why; do not mark it passed.

1. `uv sync`, `uv run ruff check .` and `uv run pytest` pass. Tests cover only the pure parts (chunking, ID generation) and use no network or database.
2. The load command stops with a clear message when `MONGODB_URI` is blank (verify with `.env` unset or blank).
3. With credentials: the load command completes, and the capability check reports Atlas with vector-search support.
4. **Section-to-chunk link:** pick one section (for example `bns:103`); confirm its chunks exist, share its `section_id`, and `chunk_index` runs from 0 without gaps.
5. **Embedding dimension:** pick one embedding; confirm `len(vector)` is 1,024 and its `chunk_id` exists in `chunks`.
6. **Repeat setup:** run the command again; document counts are unchanged, no embeddings are created, and the existing vector index is reused.
7. **Index readiness:** `embeddings_vector_index` is `queryable`.
8. **Sample query:** embed one short question (for example "punishment for theft") and run a real `$vectorSearch` on `embeddings` with `limit` 3. For the top result, resolve `chunk_id` to `chunks` and `sections` and print: `chunk_id`, `section_id`, heading, and score.
9. `.env` is untracked (`git status` does not show it), no credentials appear in output, and `data/raw/` and `data/processed/` are unchanged.

Do not build broad validation, access-control tests, deployment work, or a retrieval endpoint.

## Handover

When finished, record:

- **Files created or changed.**
- **Collections and counts:** `sources`, `sections`, `chunks`, `embeddings`.
- **Chunking:** `chunking_version`, splitter, and chunk counts per act.
- **Embedding:** model, version, dimensions, and how long the first run took.
- **Index:** name, definition, and whether it was `queryable`.
- **Sample result:** top result's `chunk_id`, `section_id`, heading and score (or "pending").
- **Commands actually run** and whether each passed.
- **Open items:** anything skipped, flagged, or pending, and why.

Later stories reuse the collection names, IDs, index name, embedding choice and `access_level` field as they are, and extend them additively.

### Handover record

- **Files created or changed:** `src/building_with_rag/{mongodb_schema,chunking,load_corpus,verify_corpus}.py`, `contracts.py` (additive fields, new `EmbeddingDocument`), `tests/test_chunking.py`, `scripts/{load_corpus,verify_story_2_2}.{ps1,sh}`, `pyproject.toml` (`voyageai>=0.5.0`), `uv.lock`, `docs/architecture.md`.
- **Chunking:** `char2048-o256-v1`; 994 chunks from 908 sections (413 BNS, 581 IPC); longest chunk 2,047 characters.
- **Commands run:** `uv run ruff check .` passed; `uv run pytest` passed (19 tests); load command with no `MONGODB_URI` stopped with a clear prerequisite message (check 2).
- **Pending (no `.env` with credentials on this machine):** checks 3-8: Atlas capability, load, section link, embedding dimension, repeat run, index readiness, sample `$vectorSearch`. Run `scripts/load_corpus.ps1` then `scripts/verify_story_2_2.ps1` and record the results here.
- **Open items:** the first full run is expected to take about 40 minutes (125 requests x 20 s).
