# Story 2.3: Semantic Retrieval Diagnostics

## Purpose

Build the first real course mode, `semantic`. A question is embedded with Voyage, matched against the Story 2.2 vector index in MongoDB Atlas, and the best source passages come back in `QueryResult.results` through the existing `POST /v1/query` route. The response is a diagnostic: it shows what was retrieved and why, so you can inspect the evidence before any answer is written.

This story extends Stories 1.1, 2.1 and 2.2; it does not replace them. Keep the existing `QueryRequest`, `QueryResult`, `RetrievedChunk`, `SemanticFilters`, `/v1/query`, the pattern registry, the mode-to-model mapping, the MongoDB document model, and the `.env.example` contract (including `MONGODB_URI`, `MONGODB_DB_NAME`, `VOYAGE_API_KEY`). Add no settings and rename nothing.

Out of scope: LLM answer generation, Open WebUI answer behavior, hybrid or keyword search, re-ranking, an evaluation harness, multi-user authorization, and broad testing. Those are later stories.

## Prerequisites

- Stories 1.1, 2.1 and 2.2 are complete: `uv sync` works, `uv run pytest` passes, and the Story 2.2 load has been run against Atlas. Story 2.2's checks 3–8 may still read "pending" in its handover; this story's verification step (below) is what proves them.
- Read first: `docs/config.yaml` (absent: no configured project path), `docs/architecture.md`, Stories 1.1, 2.1 and 2.2, `src/building_with_rag/` (`registry.py`, `patterns.py`, `contracts.py`, `app.py`, `settings.py`, `mongodb_schema.py`, `verify_corpus.py`), and `.env.example`. Preserve existing work.
- Settings come from the untracked `.env` through the existing `Settings` class. Never print, log, return or commit credentials or the connection string; print the database name only.
- The embedding choice is fixed by `docs/architecture.md` and exposed as constants in `mongodb_schema.py` (Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions). Reuse those constants; do not substitute another model, version or size.
- The demo caller is fixed and local: every request is treated as the server's demo caller (`WEBUI_DEMO_CALLER_ID`) with `access_level` `public`. Do not build multi-user authorization.

## Token-safety rule (applies to every step below)

Every verification or data-check step must be **one compact script** that prints only counts, statuses, field names and values, and vector lengths. It must **never** print vectors, embeddings, full passage text, or raw documents. Do not run ad-hoc `find`, `print(doc)` or "show me the collection" commands. If a check needs to compare text, the script compares in code and prints only a pass/fail and lengths.

## Work to do

### 1. Verify the data before retrieving

Add one small script (for example `uv run python -m building_with_rag.verify_semantic`, with `scripts/verify_story_2_3.ps1|sh` wrappers like the Story 2.2 ones). It must stop with a clear prerequisite message, and not query, if any of these fail, and print only the numbers:

- `MONGODB_URI` is blank or MongoDB is unreachable; `VOYAGE_API_KEY` is blank.
- Corpus: `sources`, `sections` (expected 908: 358 BNS, 550 IPC) and `chunks` counts, with the per-act counts.
- Embeddings: count of `embeddings` for the fixed model/version/dimensions equals the chunk count, with none missing. Check the vector length of a sample, expecting 1,024, and print only that length.
- `embeddings_vector_index` exists and is `queryable`.

Use the schema module's constants for names and settings. If the data is incomplete, tell the user to re-run `load_corpus` (it resumes); do not try to repair it here.

### 2. Semantic retrieval module

Create a small module (for example `src/building_with_rag/semantic.py`) and call it from `run_pattern` in `patterns.py` for `pattern == "semantic"` only. The other five modes keep returning their honest `not_implemented` result. Do not add a second route or a second dispatch path.

**Embed the question** with the same approved model as the documents: Voyage `voyage-3.5`, 1,024 dimensions, with `input_type="query"` (documents were embedded as documents). Use the schema constants. Check the returned vector has the fixed length before searching.

**Search** `embeddings` with `$vectorSearch` on `embeddings_vector_index`, path `vector`:

- `limit` is the request's `limit` (the existing contract already bounds it to 1–20, default 5). Choose `numCandidates` as a fixed multiple of the limit (for example `max(limit * 10, 50)`), kept as a named constant and never above Atlas's maximum. No new environment variable.
- Project only `chunk_id` and `vectorSearchScore`.
- Apply filters inside the `$vectorSearch.filter` stage, never by filtering the returned list afterwards (see step 3).

**Resolve and build results.** For each hit, load its `chunks` record by `chunk_id`, then the parent `sections` record by `section_id`, and build one `RetrievedChunk`:

| `RetrievedChunk` field | Value |
| --- | --- |
| `chunk_id` | the chunk ID, for example `bns:103#c0` |
| `section_id` | the act-qualified section ID, for example `bns:103` |
| `act` | the act code from the chunk |
| `text` | the chunk's plain `text` (not `embedding_input_text`) |
| `heading` | the section `heading` (the section title) where present |
| `score` | the `vectorSearchScore` for that hit |
| `source` | the section's `source_pdf` |
| `page` | the section's `page_start` where present |
| `chapter` | the chunk's `chapter` |

Leave `source_url` empty: nothing in the corpus provides one. Do not invent any field that is missing; use `None`. Keep results in the order MongoDB returns them (highest score first), at most `limit` items. If a chunk or section cannot be resolved, skip it, add its `chunk_id` to `omitted_candidates` with `omitted_reason` (for example `chunk_not_found`), and note it in `trace`.

**Status values.** Use these exactly, so the cases are never confused:

- `ok`: one or more passages returned.
- `no_results`: the search ran and nothing matched (including filters that leave no possible match). `results` is empty and `message` says so plainly.
- `unavailable`: a service or configuration failure: blank `MONGODB_URI` or `VOYAGE_API_KEY`, MongoDB or Voyage unreachable or erroring, the index missing or not `queryable`, or a wrong-length vector. `results` is empty, `message` says what to fix in plain words, and no secret, connection string or stack trace appears in it. Never return `no_results` for a failure.

`trace` records, in order: the mode, the embedding model and dimensions, the effective filters, `limit`/`numCandidates`, and the number of hits. Keep `QueryResult.generation` empty: no answer is generated, and `generate_answer` has no effect in this story.

A similarity score ranks passages against each other. It is **not** proof that a passage is correct, relevant to the law, or enough to answer. The `message` for an `ok` result must say these are retrieved candidates for inspection, and no code may treat a score as a pass/fail threshold.

### 3. Filters and validation

`SemanticFilters` keeps its `act`, `status` and `access_level` list fields as they are. A caller may supply any of them, and each can only **narrow** the scope:

- The server's effective scope always starts as `access_level = ["public"]`. A caller's `access_level` list is intersected with that; it can never widen it. An empty intersection (for example `["restricted"]`) means no possible match: return `no_results` without calling Voyage or MongoDB, and say why in `trace`.
- A caller's `act` and `status` lists are used as given (each value must be a string) and applied with `$in` inside the vector-search `filter`. An empty list means "no narrowing" for that field.
- **Reject** unknown filter fields (for example `chapter`, `$where`, `section_number`), operators (for example `$ne`, `$gt`), and any caller-shaped MongoDB fragment (a dict or nested object where a list of strings is expected). Do this by making `SemanticFilters` forbid extra fields and by requiring list items to be plain strings. The result is a normal 422 validation error from `/v1/query`. Do **not** reject the contract's own list fields. Never pass a caller value into the query except as a string inside an `$in` list.
- Validate the question (`QueryRequest` already limits it to 1–4,000 characters; also treat a whitespace-only question as invalid) and `limit` (1–20). Do not weaken these bounds.
- Do not use `caller_id` for any access decision beyond the fixed demo caller. `required_acts` and `chapter` on the request are not used by this mode; leave them alone.

### 4. Models list and chat

- `semantic` stays available as `rag-semantic` in `GET /v1/models` and in Open WebUI. Do not change the registry, model IDs, or the Pipe/Filter.
- `/v1/chat/completions` stays its existing placeholder until answer generation exists. With the semantic model it must not run retrieval and must not show passages to the user; it keeps returning the same honest placeholder text, and its existing tests keep passing. Choose the smallest way to do this (for example the chat route does not call retrieval while `generate_answer` is false), without duplicating retrieval code or breaking the shared `run_pattern` path used by `/v1/query`.

### 5. Architecture notes

Update `docs/architecture.md` (keep it short): the semantic retrieval flow (question → Voyage `query` embedding → `$vectorSearch` with in-database filters → resolve `chunk_id` to `chunks` and `sections` → `RetrievedChunk`), the three statuses (`ok`, `no_results`, `unavailable`), the field mapping, the note that a score is not proof of correctness, that chat remains a placeholder, and one example diagnostic command. Also replace the Story 2.2 limitation "no retrieval endpoint yet".

Example diagnostic command to record (PowerShell):

```powershell
$body = @{ question = "What is the punishment for theft?"; pattern = "semantic"; limit = 3 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/query -ContentType "application/json" -Body $body |
  Select-Object -ExpandProperty results |
  Select-Object chunk_id, section_id, act, heading, score, source, page
```

This selects fields and omits `text`, so it prints no passage bodies. Provide an equivalent for the script wrappers; do not paste responses containing passage text into notes.

## Completion checks

Keep these direct and classroom-sized. Run each and record the real result. If a service or credential is unavailable, mark that check **pending** and say why; do not mark it passed. Apart from step 1's script, each check below is run through one compact script (or the field-selecting command above) that prints only counts, statuses, field names and values, and lengths, never vectors, embeddings, full passage text or raw documents.

1. `uv sync`, `uv run ruff check .` and `uv run pytest` pass. Add only a few small tests for pure parts (filter validation and rejection, effective-scope intersection, `no_results` vs `unavailable` mapping), with no network or database.
2. **Data ready:** the step 1 script reports section, chunk and embedding counts matching, vector length 1,024, and `embeddings_vector_index` `queryable`.
3. **Natural-language question:** with the API running, one `POST /v1/query` with `pattern: semantic` and a BNS or IPC question in plain words (for example "What is the punishment for theft?") returns `status` `ok`. Print only: status, number of results, and for each result `chunk_id`, `section_id`, `act`, heading, score, source, page, and text length.
4. **No-result question:** one question with nothing relevant in an effectively empty scope (for example a valid `act` filter of `["IPC_1860"]` together with an `access_level` of `["restricted"]`) returns `no_results` with an empty `results` list. Separately, run the same query with `MONGODB_URI` or `VOYAGE_API_KEY` blank (or a deliberately wrong index name in a throwaway run) and confirm it returns `unavailable`, a different status from `no_results`. Pure semantic search rarely returns nothing for an ordinary question, so do not try to force an empty result with a nonsense question.
5. **Ordering and limit:** with `limit: 3`, at most 3 results come back, in non-increasing score order. Also confirm that an invalid `limit` (0 and 21) and an unknown filter field are rejected with a validation error.
6. **Filter in the database:** one request with `filters.act = ["BNS_2023"]` returns only BNS results; the compact print shows the set of `act` values returned.
7. **Passage against its source:** for at least one returned passage, a compact script loads its `chunks` and `sections` records and prints only booleans and lengths: the passage text equals the chunk's `text`; the chunk text is contained in the parent section's `text`; `section_id` matches the chunk; `source` equals the section's `source_pdf`; and the section's `source_sha256` is present. Print no passage text.
8. **Mode availability and chat:** `GET /v1/models` still lists `rag-semantic` (and the other five). A `POST /v1/chat/completions` for `rag-semantic` still returns the existing placeholder text and no retrieved passages. The other five modes still return `not_implemented` on `/v1/query`.
9. `.env` is untracked (`git status` does not show it), no credentials appear in any output, and `data/raw/` and `data/processed/` are unchanged.

Do not build hybrid search, re-ranking, an evaluation harness, a relevance threshold, or broad testing.

## Handover

When finished, record:

- **Files created or changed.**
- **Data check:** the counts and index status the step 1 script reported (numbers only).
- **Retrieval:** the model, dimensions, `input_type`, the `numCandidates` rule, and the three statuses.
- **Sample result:** for the natural-language question, the result count and each result's `chunk_id`, `section_id`, heading and score (no passage text), or "pending".
- **Commands actually run** and whether each passed.
- **Open items:** anything skipped, flagged or pending, and why.

Later stories reuse the `semantic` mode, the `RetrievedChunk` mapping above, the status values, and the in-database filter approach, extending them additively.
