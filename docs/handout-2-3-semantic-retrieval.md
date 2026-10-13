# Handout 2.3 — Semantic retrieval diagnostics

Paste this prompt into your coding assistant from the capstone repository:

---

Create `docs/stories/story-2-3-semantic-retrieval.md`. Create the story only; do **not** implement it. Read `docs/config.yaml`, `docs/architecture.md`, Story 1.1 and Stories 2.1–2.2, existing registry/API code, and storage/index code first. Preserve their contracts and existing work.

Write a focused implementation story in plain English with purpose, prerequisites, work to do, completion checks, and handover. It implements the first real course mode: `semantic`. It must reuse the established `QueryRequest`, `QueryResult`, `RetrievedChunk`, `/v1/query` route, pattern registry, model mapping, MongoDB document model, and project `.env.example` contract, including its MongoDB and Voyage names. It returns source passages in `QueryResult.results` only; LLM answer generation and Open WebUI answer behavior are later stories.

Require the implementer to verify the corpus, chunks, embeddings, and ready vector index before retrieving. Embed the user question with the same approved model and query settings as document embeddings. Query MongoDB vector search with a bounded configurable top-k. Return an inspectable diagnostic response containing selected mode, query, matching chunk text, score, chunk ID, act-qualified section ID, title where available, and source details. A no-result outcome must be distinct from a service/configuration failure. Do not treat a similarity score as proof of correctness.

Keep the story token-safe: every verification or data-check step must say to run one compact script that prints only counts, status, field names/values, and vector lengths. The story must forbid printing vectors, embeddings, full passage text, or raw documents.

Maintain the compatible `SemanticFilters` contract: a caller may supply `act`, `status`, and `access_level` only as lists that narrow the effective scope, and those filters must be applied in the database query. Reject unknown filter fields, operators, or caller-shaped MongoDB fragments; do not reject the contract’s own list fields. This course uses one fixed local demo caller and public access level rather than teaching multi-user authorization. Validate the question and limit; do not invent source fields that are missing.

Require a few direct checks only: one natural-language BNS or IPC question, one no-result question, response ordering/limit, and inspection of at least one returned passage against its source. Keep the same `semantic` mode available to `/v1/models` and Open WebUI, but leave chat as its existing placeholder until answer generation. Update `docs/architecture.md` with the retrieval flow and example diagnostic command. No hybrid search, re-ranking, evaluation harness, or broad testing. After creating the story, report its path only.
