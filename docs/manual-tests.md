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
