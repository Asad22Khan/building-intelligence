# Manual tests

## Story 1.1 — Architecture and Project Seed

**What it adds:** a FastAPI service that starts without credentials and exposes `/healthz`, `/v1/query`, `/v1/models` and `/v1/chat/completions`, with honest `not_implemented` placeholders for all six modes.

Start the API first: `uv run uvicorn building_with_rag.app:app` (listens on `http://127.0.0.1:8000`). Commands below are for bash; on Windows PowerShell use `curl.exe` and escape the JSON quotes, or use Git Bash.

```bash
# Health
curl -s http://127.0.0.1:8000/healthz
```

Expected: `{"status":"ok"}` with no settings or secrets.

```bash
# Query (success: placeholder result)
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is theft?", "pattern": "semantic"}'

# Query (failure: empty question)
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "", "pattern": "semantic"}'
```

Expected: the first returns a `QueryResult` with `pattern` `semantic`, `status` `not_implemented`, a message and empty `results`. The second returns HTTP 422 with a validation `detail`.

```bash
# Models
curl -s http://127.0.0.1:8000/v1/models
```

Expected: an OpenAI-style list of six models: `rag-semantic`, `rag-hybrid`, `rag-hybrid-reranked`, `rag-structured`, `rag-decomposition`, `rag-hyde`.

```bash
# Chat, non-streaming (success)
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-semantic", "stream": false, "messages": [{"role": "user", "content": "What is theft?"}]}'

# Chat, streaming
curl -s -N -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-semantic", "stream": true, "messages": [{"role": "user", "content": "What is theft?"}], "rag_options": {"pattern": "semantic", "limit": 5}}'

# Chat (failure: unknown model)
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-unknown", "messages": [{"role": "user", "content": "hi"}]}'
```

Expected: the first returns normal chat-completion JSON whose message says the `semantic` pattern is not implemented. The second streams a role frame, a content frame with the same text, a stop frame, and ends with `data: [DONE]`. The third returns HTTP 404 with an OpenAI-style `{"error": {...}}` envelope (`code` `model_not_found`).

```bash
# Every selectable mode (rag-semantic ... rag-hyde)
for m in rag-semantic rag-hybrid rag-hybrid-reranked rag-structured rag-decomposition rag-hyde; do
  curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"$m\", \"messages\": [{\"role\": \"user\", \"content\": \"What is theft?\"}]}"
  echo
done
```

Expected: six JSON responses, each with `model` set to that ID and a message saying its pattern is not implemented.

## Story 2.3 — Semantic Retrieval Diagnostics

**What it adds:** the real `semantic` mode on `POST /v1/query`, which embeds the question with Voyage, runs an Atlas `$vectorSearch`, and returns source passages in `results` (no generated answer).

Start the API first: `uv run uvicorn building_with_rag.app:app`. Needs `MONGODB_URI` and `VOYAGE_API_KEY` set in `.env` and the Story 2.2 load finished. Commands below are for bash; on Windows PowerShell use `curl.exe` and escape the JSON quotes, or use Git Bash.

```bash
# Semantic query (success)
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "limit": 3}'

# Semantic query narrowed to BNS only
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "limit": 3, "filters": {"act": ["BNS_2023"]}}'
```

Expected: `pattern` `semantic`, `status` `ok`, and at most 3 `results` ordered by descending `score`, each with `chunk_id`, `section_id`, `act`, `heading`, `text`, `source` and `page`; `generation` is null. The second returns only `act` `BNS_2023` results. Scores rank passages and are not proof of correctness.

```bash
# No-result: filters leave no possible match
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "filters": {"act": ["IPC_1860"], "access_level": ["restricted"]}}'

# Failure: unknown filter field
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "filters": {"chapter": ["I"]}}'

# Failure: limit out of range
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "limit": 21}'
```

Expected: the first returns `status` `no_results` with empty `results`. The second and third return HTTP 422 with a validation `detail`. With `MONGODB_URI` or `VOYAGE_API_KEY` blank, a valid semantic query returns `status` `unavailable` (not `no_results`) and a message naming the missing setting.

```bash
# Chat for rag-semantic (placeholder until Story 3.2, which connects it)
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-semantic", "stream": false, "messages": [{"role": "user", "content": "What is the punishment for theft?"}]}'
```

Expected at Story 2.3: placeholder text only; superseded by Story 3.2 (answer, confidence and sources).

## Story 3.1 — Grounded Answer Generation

**What it adds:** `generate_answer: true` on `POST /v1/query` (`semantic` mode) turns the retrieved passages into a non-streaming, cited answer in `generation`, or an honest insufficient-evidence, unavailable or malformed outcome.

Start the API first: `uv run uvicorn building_with_rag.app:app`. Needs `MONGODB_URI` and `VOYAGE_API_KEY` for retrieval, plus `GENERATION_API_BASE_URL` and `GENERATION_API_KEY` (the trainer's OpenAI-compatible proxy) set in `.env`. Commands below are for bash; on Windows PowerShell use `curl.exe` and escape the JSON quotes, or use Git Bash.

```bash
# Answerable question (success)
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "limit": 5, "generate_answer": true}'
```

Expected: `status` `ok` with the retrieved `results`, and `generation.outcome` `answered` with a non-empty `answer`, `claims` (each with `evidence` labels such as `E1`), and `citations` (each with `label`, `chunk_id`, `section_id`, `act`, `heading`, `source`, `page`) that match entries in `results`. `generation.context_outcome` is `ok` or `truncated`.

```bash
# Unsupported question (edge case)
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the penalty for a GDPR data breach?", "pattern": "semantic", "limit": 5, "generate_answer": true}'

# generate_answer false: retrieval only
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for theft?", "pattern": "semantic", "limit": 3}'
```

Expected: the first returns `generation.outcome` `insufficient_evidence` with `answer` null and the retrieved `results` still shown. The second returns the Story 2.3 result with `generation` null.

With `GENERATION_API_BASE_URL` or `GENERATION_API_KEY` blank, the first command returns retrieval `status` `ok`, `generation.outcome` `unavailable` and `answer` null. A reply the app cannot use gives `malformed` with `answer` null. No answer is ever invented.

```bash
# Chat for rag-semantic (Story 3.2 connects it to generation; see Story 3.2 below)
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-semantic", "stream": false, "messages": [{"role": "user", "content": "What is the punishment for theft?"}]}'
```

Expected (since Story 3.2): normal chat-completion JSON whose message is a `DRAFT — checking evidence` answer ending with a confidence and `Sources:` block (needs retrieval and generation settings; otherwise an `unavailable` message).
