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
- `POST /v1/chat/completions`: maps the model and `rag_options` to the same `QueryRequest` and the same `run_pattern` path. The server sets the demo caller ID and `generate_answer`. Open WebUI receives only plain answer text derived from the same `QueryResult`. Supports JSON and SSE streaming.

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
