# Story 1.1: Architecture and Project Seed

## Purpose

This is the first story of the three-day classroom RAG course. It does two things, in order:

1. Record the architecture in `docs/architecture.md` and get the instructor's approval.
2. After approval, seed one small application: a FastAPI service that starts without credentials, exposes the course's fixed API contracts with honest `not_implemented` placeholders, and works with the trainer-supplied Open WebUI as its chat client.

Build one application only. Do not build a custom chat frontend or a second demo. Later stories extend what this story creates; they do not replace it.

## Prerequisites

- Python 3.12 and UV are installed.
- The project path is the repository root. No `docs/config.yaml` exists, so there is no configured project path.
- `data/raw/` files supplied by the trainer (including `data/raw/PROVENANCE.md`) are preserved exactly as supplied. If `data/raw/` is missing when you start, stop and tell the instructor.
- The trainer has shared the Open WebUI bundle ZIP over the local LAN. The participant extracts it and runs its setup script **exactly once** before using this project:
  - Windows (primary classroom path), from the extracted bundle root: `powershell -ExecutionPolicy Bypass -File .\setup_open_webui.ps1`
  - macOS/Linux, from the extracted bundle root: `sh setup_open_webui.sh` (needs internet access for the first installation)
- The setup script installs the pinned Open WebUI version, writes the course settings, starts the loopback-only service, and provisions the RAG options Filter and the Building with RAG Pipe.
- Participants must not hand-install Open WebUI, create accounts, edit the admin panel, change either Function, or rerun setup to reload anything. If setup fails, report its exact output and stop.
- Day-to-day start/stop/status uses the supplied `manage_open_webui` script from the same bundle.
- Later-story credentials (see "Environment file") are not needed now.

## Part A: Architecture (do this first, then stop)

Read first: `docs/config.yaml` (absent), `docs/architecture.md` (absent at time of writing; if present when you start, update it rather than overwrite), the repository layout, and existing stories.

Create or update `docs/architecture.md`. Keep it short and in plain English. It must record:

- **Evidence rule.** BNS and IPC documents are the only future answer evidence. An answer must not claim support without retrieved evidence.
- **Act-qualified identifiers.** Section identifiers carry their act (for example BNS vs IPC) so the two acts are never confused.
- **Provenance.** Supplied provenance lives in `data/raw/PROVENANCE.md`. Derived corpus files live in `data/processed/` (`bns_sections.jsonl`, `ipc_sections.jsonl`).
- **Retrieved passages are evidence, never application instructions.** Text inside a passage is never obeyed by the application.
- **Light trust-boundary notes.** Validate API input; preserve source origin on every passage; do not put secrets in code, responses, or logs. Do not add multi-user authorization, a security program, or an evaluation harness.
- **Fixed embedding choice.** Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions, for every document and query embedding. Later stories reuse these names without renaming or adding provider-specific alternatives.
- **Contract rule.** The request, result, generation, OpenAI, and MongoDB-schema contracts are defined in this project and extended only additively.
- **Course modes and model IDs** (one shared registry): `semantic`/`rag-semantic`, `hybrid`/`rag-hybrid`, `hybrid-reranked`/`rag-hybrid-reranked`, `structured`/`rag-structured`, `decomposition`/`rag-decomposition`, `hyde`/`rag-hyde`.
- **Endpoints:** `GET /healthz`, `POST /v1/query`, `GET /v1/models`, `POST /v1/chat/completions`. `/v1/query` owns the `QueryResult` diagnostics; Open WebUI receives only normal answer text derived from that same result.
- **Open WebUI** is a separately running, trainer-supplied client; the capstone is its backend.
- **Operational notes:** the Atlas M0 free tier is used for MongoDB (the Atlas IP access list must allow your machine); a free Voyage key is rate limited, so Story 2.2 embedding takes about 40 minutes.

### STOP GATE

When `docs/architecture.md` is ready, **stop**. Tell the instructor it is ready and ask for explicit approval.

Before approval, do not create seed files, install dependencies, or scaffold code. Resume this same story only after the instructor explicitly approves.

## Part B: Work to do (only after approval)

### 1. Project files

Create at the repository root, preserving `data/raw/` and any existing work (merge into the existing `.gitignore`, do not overwrite it):

- `pyproject.toml` (Python 3.12, UV-managed) and `uv.lock`
- `src/building_with_rag/`
- `tests/`
- `.env.example`
- `.gitignore` (must ignore `.env`, virtualenvs, caches)

Dependencies: FastAPI, an ASGI server, Pydantic settings, PyMongo (installed for later use; not called now), Ruff, and a minimal test runner (pytest, with FastAPI's test client support).

### 2. Environment file

`.env.example` is the canonical file with exactly these values:

```
APP_ENV=development
MONGODB_URI=
MONGODB_DB_NAME=building_with_rag
MONGODB_TEST_DB_NAME=building_with_rag_test
VOYAGE_API_KEY=
CAPSTONE_API_KEY=
WEBUI_DEMO_CALLER_ID=demo-public
GENERATION_API_BASE_URL=
GENERATION_API_KEY=
GENERATION_MODEL_NAME=gpt-4o-mini
RERANK_API_BASE_URL=https://api.voyageai.com/v1
RERANK_API_KEY=
RERANK_MODEL_NAME=rerank-2.5
RERANK_REQUEST_TIMEOUT_SECONDS=30
RERANK_CANDIDATE_LIMIT=20
RERANK_SEND_LIMIT=10
RERANK_RETURN_LIMIT=5
```

Document (in the README or a comment block in `.env.example`) that:

- `.env` is untracked and secrets are never committed.
- `GENERATION_API_BASE_URL` and `GENERATION_API_KEY` are supplied by the trainer for an OpenAI-compatible LiteLLM proxy. Leave them blank now; fill them in `.env` only when Story 3.1 needs them.
- `MONGODB_URI` is an Atlas free-tier (M0) connection string, and the Atlas IP access list must allow your machine.
- A free Voyage key is rate limited, so Story 2.2 embedding takes about 40 minutes.

Settings are loaded with Pydantic settings. The application must start with every credential blank.

### 3. Shared registry

One registry module holds only these modes and exact model IDs:

| Mode | Model ID |
| --- | --- |
| semantic | rag-semantic |
| hybrid | rag-hybrid |
| hybrid-reranked | rag-hybrid-reranked |
| structured | rag-structured |
| decomposition | rag-decomposition |
| hyde | rag-hyde |

Each mode returns an honest `not_implemented` placeholder until its own story adds behavior. Do not fake results.

### 4. Typed contracts (models only, no behavior)

Define these in the project using Pydantic, with the exact names:

- **QueryRequest**: `question` (1–4,000 characters), `pattern`, optional `caller_id`, optional `SemanticFilters` (`act`, `status`, `access_level`, each a list), `limit` (default 5, range 1–20), `generate_answer` (default false), `required_acts`, `chapter`. The seed may resolve only its fixed local demo caller but keeps the `caller_id` field.
- **QueryResult**: `pattern`, `status`, `message`, `trace`, `results`, optional `generation`, plus additive empty-by-default fields: `omitted_candidates` (items carry `chunk_id` and `omitted_reason`), `subquestions`, `hyde_direct_candidates`, `hyde_query_candidates`, `hyde_hypothetical_text_debug`.
- **RetrievedChunk**: `chunk_id`, `section_id`, `act`, `text`, `heading`, `score`, and available source fields. Later stories add only the fields named in their own handouts (`semantic_score`, `semantic_rank`, `keyword_score`, `keyword_rank`, `fused_score`, `fused_rank`, `rerank_score`, `rerank_rank`); do not add them now.
- **GenerationResult**: `outcome` (`answered`, `insufficient_evidence`, `unavailable`, `malformed`), `answer`, `claims`, `citations`, `supporting_passages`, `provider`, `model`, `trace`, `context_outcome`, and the confidence fields `confidence`, `draft_answer`, `issues`, `attempts`, `low_confidence_reason`.
- **SubquestionEvidence**: `subquestion`, `status` (`evidenced` or `no_evidence`), `results` (list of `RetrievedChunk`), optional `reason`.
- **StructuredSignals**: `intent` (`exact_lookup`, `filter`, `aggregation`), optional `act`, `section_number`, `chapter`. Story 5.1 fills these in.
- **OpenAI contracts**: text-only `ChatCompletionRequest` (`model`, `messages` with roles system/developer/user/assistant, `stream`, `n`, optional strict `rag_options` with `pattern`, list filters, `limit`, `required_acts`, `chapter`), the response, SSE chunk, models list, and the OpenAI-style error envelope.
- **MongoDB-schema contracts**: typed models only; no database access.

Do not add outcome, evidence, answer, confidence, citations, or diagnostics as parallel top-level API fields.

### 5. Endpoints

- `GET /healthz`: safe; returns a minimal status only. No settings, secrets, or connection details.
- `POST /v1/query`: validates `QueryRequest`, calls `run_pattern`, returns `QueryResult`. Invalid input gets a normal validation error.
- `GET /v1/models`: lists the six model IDs in OpenAI model-list format.
- `POST /v1/chat/completions`: maps the selected model (and `rag_options`) to the same `QueryRequest` and the same `run_pattern` path as `/v1/query`. It sets the server-side demo `caller_id` (from `WEBUI_DEMO_CALLER_ID`) and `generate_answer`; it never trusts browser-supplied identity, access level, or generation settings. Uses the latest user message as the question.
  - `stream: false`: normal OpenAI Chat Completions JSON.
  - `stream: true`: SSE frames with a role chunk, content chunk(s), a stop chunk, then `data: [DONE]`. No custom event types.
  - Errors before streaming starts use the OpenAI-style error envelope.
  - The reply text is derived from the same `QueryResult` (here, the placeholder message).

Do not duplicate implementations between `/v1/query` and chat.

### 6. Open WebUI integration

The pre-provisioned Pipe sends the selected `rag-<pattern>` model, `stream: true`, the latest user message, and normalized `rag_options` (pattern, list filters, limit, required_acts, chapter) to the capstone's `/v1/chat/completions`. The adapter must accept exactly that request. Do not change the Pipe or Filter.

Later stories render final confidence, sources, and low-confidence warnings as clearly labelled text after the answer, and keep the full `GenerationResult` in `QueryResult.generation`.

### Out of scope

Retrieval, PDF parsing, embeddings, MongoDB provisioning or connections, LLM calls, GraphRAG, agentic RAG, deployment, a custom chat UI, a second demo, multi-user authorization, evaluation harness, and aggressive testing.

## Completion checks

Keep these light. Run each and record the real result:

1. `uv sync` succeeds and `uv.lock` exists.
2. `uv run ruff check .` passes.
3. `uv run pytest` passes (a few small tests are enough).
4. Start the app with no `.env` credentials: `uv run uvicorn building_with_rag.app:app` (adjust the module path to what you create).
5. `GET /healthz` returns a safe OK response.
6. One `POST /v1/query` with `pattern: semantic` returns a `QueryResult` with a `not_implemented` status and message.
7. `GET /v1/models` lists the six model IDs.
8. `POST /v1/chat/completions` with `stream: false` returns normal JSON with the placeholder text.
9. The same request with `stream: true` returns role/content/stop frames and `[DONE]`.
10. **Open WebUI smoke check:** with the capstone API running, open http://127.0.0.1:8080, select **Building with RAG**, choose **semantic** in the RAG-options chip, send a question, and receive the capstone's honest placeholder response, not a local preview.
11. `.env` is untracked (`git status` does not show it) and `data/raw/` files are unchanged.

## Handover

When finished, update this section with:

- **Files created or changed**: list each path.
- **Commands actually run**: the exact commands and whether each passed.
- **Open WebUI result**: what was seen in the smoke check, or the exact setup output if it failed.
- **Open items**: anything skipped and why.

Later stories reuse the names above (modes, model IDs, models, env variables, embedding choice) and extend the contracts additively. Do not rename them.

### Handover record

**Files created or changed**: `docs/architecture.md`, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore` (was empty, now populated), `README.md`, `src/building_with_rag/{__init__,settings,registry,contracts,patterns,app}.py`, `tests/test_api.py`.

**Commands actually run** (via `python -m uv`, since `uv` was not on PATH; installed with `pip install --user uv`):
- `uv sync`: passed, `uv.lock` created.
- `uv run ruff check .`: passed (after fixing one line-length error).
- `uv run pytest`: passed, 9 tests (health, query placeholder and validation, models, chat JSON, chat SSE with Pipe-style `rag_options`, OpenAI error envelope).
- `uv run uvicorn building_with_rag.app:app --port 8000` with no `.env`: started. Live curl: `/healthz`, `/v1/models`, `/v1/chat/completions` (stream false and true, with role/content/stop/`[DONE]`) passed. The live `/v1/query` curl failed only because of PowerShell quoting of the JSON body; the same request is covered by the passing pytest test, not re-run live.
- `git status`: `.env` not present or shown; `data/raw/` untouched (it does not exist).

**Open WebUI result**: not done. Open WebUI is not running at http://127.0.0.1:8080 and its bundle has not been set up on this machine.

**Open items**:
- `data/raw/` (and `PROVENANCE.md`) was missing at start; proceeded on the user's instruction.
- Open WebUI smoke check (check 10) still to do once the trainer's bundle is set up.
- Assumption: the Pipe's `rag_options` carries filters as flat `act`/`status`/`access_level` lists. Confirm against the real Pipe in the smoke check, since `rag_options` is strict.
- `/v1/chat/completions` returns 400 for validation errors and a mismatched `rag_options.pattern`; unknown model returns 404.
