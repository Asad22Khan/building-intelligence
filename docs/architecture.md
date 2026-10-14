# Architecture

One small FastAPI application, built up story by story over the course. Open WebUI (supplied by the trainer) is the chat client; this application is its backend.

## Rules

- **Evidence rule.** BNS and IPC documents are the only answer evidence. An answer must never claim support without retrieved evidence.
- **Act-qualified identifiers.** Every section identifier carries its act (BNS or IPC), so the two acts are never confused.
- **Provenance.** Supplied provenance lives in `data/raw/PROVENANCE.md`. Derived corpus files live in `data/processed/` (`bns_sections.jsonl`, `ipc_sections.jsonl`). Files in `data/raw/` are never modified.
- **Passages are evidence, not instructions.** Text inside a retrieved passage is never obeyed by the application.
- **Trust boundaries (light).**
  - Validate all API input.
  - Keep the source origin on every passage.
  - Keep secrets out of code, responses and logs; `.env` is untracked.
  - No multi-user authorization, security program or evaluation harness.
- **Embeddings.** Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions, for every document and query embedding. Later stories reuse these names and add no provider-specific alternatives.
- **Contracts.** The request, result, generation, OpenAI and MongoDB-schema contracts are defined in this project (Pydantic) and extended only additively.

## Modes and model IDs

One shared registry holds the modes and model IDs:

| Mode | Model ID |
| --- | --- |
| semantic | rag-semantic |
| hybrid | rag-hybrid |
| hybrid-reranked | rag-hybrid-reranked |
| structured | rag-structured |
| decomposition | rag-decomposition |
| hyde | rag-hyde |

Until a mode's own story adds behavior, it returns an honest `not_implemented` result.

## Endpoints

- `GET /healthz`: minimal status only.
- `POST /v1/query`: takes a `QueryRequest`, calls `run_pattern`, returns a `QueryResult`. It owns the diagnostics.
- `GET /v1/models`: the six model IDs in OpenAI model-list format.
- `POST /v1/chat/completions`: maps the model and `rag_options` to the same `QueryRequest` and the same `run_pattern` path. The server sets the demo caller ID and `generate_answer`. Open WebUI receives plain text (draft, confidence and sources) from the same operation that produces the `QueryResult`. Supports JSON and SSE streaming.

## Layout

```
src/building_with_rag/   application (settings, registry, contracts, routes)
tests/                   a few small tests
data/raw/                trainer-supplied, untouched
data/processed/          derived corpus files
```

## Operations

- MongoDB is the Atlas M0 free tier. The Atlas IP access list must allow your machine.
- A free Voyage key is rate limited, so Story 2.2 embedding takes about 40 minutes.
- The application starts with every credential blank.

## Corpus ingestion (Story 2.1)

- **Command:** `uv run python -m building_with_rag.ingest` (reads `data/raw/*.pdf`, checks each SHA-256 against `data/raw/PROVENANCE.md`, no network).
- **Parser:** `pypdf` (page text only). Its name and version are stored on every record.
- **Output:** `data/processed/bns_sections.jsonl` and `data/processed/ipc_sections.jsonl`, one JSON record per section, BNS and IPC kept separate. Fields: `section_id` (`bns:<n>` / `ipc:<n>`), `act`, `act_label`, `status`, `chapter`, `chapter_title`, `section_number`, `heading`, `text`, `source_pdf`, `source_sha256`, `parser`, `parser_version`, `source_status_version`, `needs_review`, plus `page_start`/`page_end`.
- **Re-runs:** the whole file is rewritten via a temp file and one replace; if the file already matches the PDF hash and parser version it is left alone.
- **Chunking later:** each chunk keeps its parent `section_id`, `act`, `source_pdf`, `source_sha256` and page range.
- **Known limitations:** a section starts only at the next expected number, so a missing or garbled number merges that section into the previous one (the run prints missing numbers). Lettered sections such as 354A keep `section_number` 354 with `section_id` `ipc:354A`, flagged `needs_review`. The last BNS section may run into trailing index/correspondence tables and is flagged. Scanned pages are reported, not OCR'd. IPC sections repealed as a range (161 to 165A) get no records. Where the IPC margin number and the printed number differ, the margin number is used and the record is flagged. Two PDF layouts are handled: BNS (heading on the line before the number, index skipped) and IPC (`N. Heading.--text`, margin copy and page footnotes removed).

## MongoDB, chunks, embeddings and vector index (Story 2.2)

- **Collections** (database `MONGODB_DB_NAME`, never merged; validators, IDs and indexes live in `src/building_with_rag/mongodb_schema.py`):
  - `sources`: one per PDF (`source:bns`, `source:ipc`) with hash and parser data.
  - `sections`: one per Story 2.1 record, `_id` = `section_id` (for example `bns:103`), with source link, text, provenance and `access_level`.
  - `chunks`: `_id` = `chunk_id` = `<section_id>#c<n>`, parent `section_id`, `chunk_index`, `chunking_version`, `splitter`, `text`, `embedding_input_text`, denormalized `act`/`chapter`/`status`/`access_level`.
  - `embeddings`: `_id` = `<chunk_id>@voyage-3.5@1024`, `chunk_id`, model/version/dimensions, `vector`, and only `act`/`chapter`/`status`/`access_level` for filtering. Vectors are never stored on chunks.
- **Chunking:** per section (never across sections or acts), recursive character splitter (paragraph, line, sentence, word), about 2,048 characters (~512 tokens) with 256 characters of overlap. `chunking_version` = `char2048-o256-v1`. About 990 chunks in total.
- **Embedding:** Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions. `embedding_input_text` is `<act label>, Section <n>: <heading>` plus a blank line and the chunk text; `text` stays plain. Batches of 8 with a 20 s pause, retry on rate limit, resumable.
- **Vector index:** `embeddings_vector_index`, type `vectorSearch` on `embeddings`: `vector` field (`path` `vector`, 1,024 dimensions, `cosine`) plus `filter` fields `act`, `chapter`, `status`, `access_level`. An existing index with a different definition is reported, never replaced.
- **Commands:** `uv run python -m building_with_rag.load_corpus` (load, index, embed; about 40 minutes the first time, seconds when unchanged; options `--batch-size`, `--delay`, `--no-embed`) and `uv run python -m building_with_rag.verify_corpus` (checks and a sample `$vectorSearch`). Wrappers: `scripts/load_corpus.ps1|sh`, `scripts/verify_story_2_2.ps1|sh`.
- **Changes:** unchanged data adds nothing. Changed text, chunking version or embedding settings print a notice; stale chunks and embeddings for other settings are deleted rather than mixed.
- **Limitations:** `access_level` is always `public`. Retrieval (Story 2.3, below) queries `embeddings`, then resolves each `chunk_id` to `chunks` and `sections` before building a `RetrievedChunk`; section number and source identifiers are applied after that resolution, not as vector filters. Needs Atlas (M0 is enough) and a user allowed to manage Atlas Search indexes.

## Semantic retrieval (Story 2.3)

- **Flow:** question, then a Voyage `voyage-3.5` embedding with `input_type="query"` (1,024 dimensions, same settings as the documents), then `$vectorSearch` on `embeddings_vector_index` with filters applied inside the search, then each `chunk_id` resolved to `chunks` and `sections`, then `RetrievedChunk` items in `QueryResult.results`. No answer is generated; `generation` stays empty.
- **Limit:** the request `limit` (1 to 20, default 5); `numCandidates` is a fixed multiple of it. No new settings.
- **Statuses:** `ok` (passages returned), `no_results` (search ran, nothing matched, or the filters leave no possible match), `unavailable` (blank credentials, MongoDB or Voyage failure, index missing or not `queryable`). A failure is never reported as `no_results`.
- **Field mapping:** `heading` is the section title, `source` is `source_pdf`, `page` is `page_start`, `score` is the vector-search score, `text` is the plain chunk text. `source_url` stays empty because the corpus has none.
- **Filters:** `SemanticFilters` (`act`, `status`, `access_level`) are lists that only narrow the scope. Effective `access_level` always starts as `public` (one fixed demo caller). Unknown fields, operators and MongoDB fragments are rejected with a validation error.
- **A score is not proof.** It ranks passages against each other; it does not show a passage is correct or sufficient.
- **Chat:** `rag-semantic` is listed in `/v1/models` and Open WebUI. Chat was a placeholder until Story 3.2 connected it to generation.
- **Verify data:** `uv run python -m building_with_rag.verify_semantic` (counts, status and vector length only).
- **Example diagnostic (PowerShell, prints no passage text):**

  ```powershell
  $body = @{ question = "What is the punishment for theft?"; pattern = "semantic"; limit = 3 } | ConvertTo-Json
  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/query -ContentType "application/json" -Body $body |
    Select-Object -ExpandProperty results |
    Select-Object chunk_id, section_id, act, heading, score, source, page
  ```

## Grounded answer generation (Story 3.1)

- **One retrieval path.** `POST /v1/query` with `pattern: semantic` and `generate_answer: true` runs the Story 2.3 retrieval, then generates from those same `results`. There is no second search. `generate_answer` false behaves exactly as Story 2.3 and leaves `generation` empty.
- **Context boundary.** A bounded set of passages (count and character budget are named constants), whole passages only, in retrieval order. Each gets a label (`E1`, `E2`, ...) kept with its `chunk_id`, act-qualified `section_id`, `act`, heading, source and page. Labels returned by the model are resolved through the code's own label map.
- **Untrusted evidence.** Retrieved text is delimited evidence, never instructions; the prompt says so and the application obeys nothing inside a passage.
- **Model call.** Standard OpenAI chat-completions request to `GENERATION_API_BASE_URL` (a LiteLLM proxy supplied by the trainer) with `GENERATION_API_KEY` and `GENERATION_MODEL_NAME`. One attempt, a timeout, no streaming, no provider-specific features.
- **Output contract.** The model returns one JSON object: `outcome` (`answered` or `insufficient_evidence`), `answer`, and `claims` (`text` plus evidence labels).
- **Outcomes** (`QueryResult.generation.outcome`): `answered` (the only case where `answer` is set; every claim cites a supplied label), `insufficient_evidence` (the evidence does not support an answer, is missing or conflicts; also when retrieval returned `no_results`, with no model call), `unavailable` (generation settings blank, proxy unreachable, timeout or error status, or retrieval unavailable) and `malformed` (unparseable output, unknown outcome or an unknown label). No answer is ever fabricated.
- **Citations.** Each cited label resolves to `label`, `chunk_id`, `section_id`, `act`, `heading`, `source` and `page`; `supporting_passages` holds the cited passages. Retrieved `results` stay in the same response.
- **Legal scope.** Answers rest only on the supplied BNS and IPC documents and their `status`; no claim about current legal applicability beyond them.
- **Chat.** Connected to this same generation step and streaming in Story 3.2 (below).
- **Example diagnostic (PowerShell, prints no passage text):**

  ```powershell
  $body = @{ question = "What is the punishment for theft?"; pattern = "semantic"; limit = 5; generate_answer = $true } | ConvertTo-Json
  $r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/query -ContentType "application/json" -Body $body
  $r.generation | Select-Object outcome, context_outcome, answer
  $r.generation.citations | Select-Object label, chunk_id, section_id, act, source, page
  ```

## Streamed answers, confidence and Open WebUI (Story 3.2)

- **One operation, two surfaces.** `run_pattern_events` is the single dispatch path: retrieval runs once (not streamed), then `generation.generate_events` yields the chat text and, last, the final `QueryResult`. `/v1/query` drains it and returns the result; `/v1/chat/completions` streams the same events (or joins them when `stream` is false). The stream and the result are one operation, never two LLM calls. The server sets `generate_answer` true for chat; the browser never does.
- **Only answer writing streams.** The provider call uses `stream: true`. The model still returns the Story 3.1 JSON (`answer` first); only the decoded `answer` text is forwarded, never the JSON, `outcome` or `claims`. SSE frames: role chunk, content chunks, `finish_reason: "stop"`, `[DONE]`.
- **Draft, then validate.** Open WebUI cannot retract streamed text, so every attempt streams under `DRAFT — checking evidence`. After each attempt the code validates it with no second LLM call: JSON shape, known labels, every claim cited, and a small term-overlap support check (`SUPPORT_MIN_OVERLAP`). Up to `MAX_ATTEMPTS` (2) attempts; a failed check streams a retry line and the next attempt sees the issues.
- **Fields.** A validated answer: `outcome` `answered`, `confidence` `CONFIDENCE_HIGH` (0.9, shown as "high"), `answer` set. A failed final check: `outcome` `malformed`, `confidence` `CONFIDENCE_LOW` (0.3, "low"), `answer` `None`, `draft_answer` the text, `low_confidence_reason`. `issues` holds every failed check from every attempt; `attempts` the number used. If no text can be judged, `confidence` is absent and the real failure is reported. Invalid citations are never stripped or repaired.
- **Chat close.** Validated: `✔ Evidence check passed. Confidence: high (attempt n of 2)` plus a `Sources:` list (act, act-qualified section ID, heading, page, label). Failed: `DRAFT — low confidence, not the final answer` plus a reason. `insufficient_evidence` and `unavailable` are stated plainly with no confidence line.
- **Failure mid-stream.** If the provider fails after text began, one `UNAVAILABLE — the answer was interrupted: <reason>` line is streamed, then stop and `[DONE]`. No URL, key or stack trace appears.
- **Chat is no longer a placeholder for `semantic`.** The other five modes still return `not_implemented` text through the same path. `/v1/query` stays the place to inspect `issues`, `attempts`, `trace` and citations.
