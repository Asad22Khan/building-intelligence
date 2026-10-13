# building-intelligence

Capstone backend for the Building with RAG course (BNS/IPC). See `docs/architecture.md`.

## Run

```
uv sync
uv run uvicorn building_with_rag.app:app
uv run pytest
uv run ruff check .
```

## Environment

Copy `.env.example` to `.env`. The app starts with every credential blank.

- `.env` is untracked; secrets are never committed.
- `GENERATION_API_BASE_URL` and `GENERATION_API_KEY` are supplied by the trainer (OpenAI-compatible LiteLLM proxy). Leave blank until Story 3.1.
- `MONGODB_URI` is an Atlas free-tier (M0) connection string; the Atlas IP access list must allow your machine.
- A free Voyage key is rate limited, so Story 2.2 embedding takes about 40 minutes.

## Open WebUI

Trainer-supplied and set up once from its bundle. Use http://127.0.0.1:8080 and the **Building with RAG** model; it calls this API's `/v1/chat/completions`.
