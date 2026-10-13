# Handout 3.1 — Grounded answer generation

Paste this prompt into your coding assistant from the capstone repository:

---

Create `docs/stories/story-3-1-grounded-answer-generation.md`. Create the story only; do **not** implement it. Read `docs/config.yaml`, `docs/architecture.md`, Story 1.1 and Stories 2.1–2.3, existing semantic retrieval, `/v1/query`, chat adapter, and generation code first. Preserve the shared registry and endpoints.

Write a small implementation story with purpose, prerequisites, work to do, completion checks, and handover. It turns the existing semantic retrieval result into a grounded non-streaming answer. It must use the exact evidence returned by semantic retrieval, not a second retrieval path. Streaming confidence and Open WebUI answer streaming are the next story.

Require context assembly that selects a bounded set of retrieved passages and retains their labels, chunk IDs, act-qualified section IDs, and source details. Require answer generation through the existing `GENERATION_API_BASE_URL`, `GENERATION_API_KEY`, and `GENERATION_MODEL_NAME` settings in the project’s `.env.example`; preserve their names and default. The trainer supplies the base URL and key for an OpenAI-compatible LiteLLM proxy; call it with the standard chat-completions format, without adding provider-specific replacements. If generation configuration is absent, the provider times out, or its output cannot be parsed, return a distinct honest unavailable/malformed outcome with no fabricated answer. The prompt must make clear that retrieved text is untrusted evidence, not application instructions.

The model output must distinguish a supported answer from insufficient evidence. Preserve the compatible nested `GenerationResult` in `QueryResult.generation`: its `answer` is populated only for `outcome="answered"`; claims, resolved citations, supporting passages, provider/model metadata, trace, and context outcome retain their existing field names. A supported answer cites only supplied evidence labels and resolves them to act-qualified citations in that nested result. An unsupported, missing, or conflicting-evidence question must return a clear insufficient-evidence outcome rather than a guessed answer. Do not claim current legal applicability beyond the supplied documents.

Expose the result through the same `/v1/query` response alongside the retrieved evidence, answer outcome, and citations. Preserve the OpenAI-compatible route and its placeholder behavior for this story; it will be connected to real generation in Story 3.2. Keep the design simple: no automatic routing, follow-up memory, broad evaluation harness, multi-user controls, or production observability.

Require direct checks for one answerable question with valid citations and one unsupported question. Inspect the citations against the supplied context and show the diagnostic response. Update `docs/architecture.md` with context and answer boundaries. After creating the story, report its path only.
