# Handout 4.1 — Hybrid search [Keyword and Semantic]

Paste this prompt into your coding assistant from the capstone repository:

---

Create `docs/stories/story-4-1-hybrid-search.md`. Create the story only; do **not** implement it. Read the architecture, all prior stories, the semantic pattern, MongoDB setup, diagnostics, and chat adapter first. Preserve the working semantic mode and shared answer path.

Write a focused implementation story with purpose, prerequisites, work to do, completion checks, and handover. It adds the `hybrid` mode for questions where exact legal terms or section language complement semantic similarity. It must use the same corpus, MongoDB deployment, evidence shape, context assembly, citations, `/v1/query`, model mapping, Open WebUI streaming path, and project `.env.example` contract as semantic RAG.

First identify the configured MongoDB deployment’s supported keyword-search capability and use its documented query/index mechanism against the stored chunk-text field; record the exact field and index requirement. Combine those candidates with semantic candidates through an explicit, documented fusion rule. Keep candidate source metadata and scores inspectable, including which retrieval route contributed a candidate. Do not change the embedding model, regenerate the corpus, or create a second application. If keyword-search capability is unavailable, report the prerequisite and retain the semantic mode unchanged.

Expose `hybrid` as an explicitly selectable registry/model mode; do not add automatic routing. Preserve `QueryResult` and add only the compatible hybrid fields to each `RetrievedChunk`: `semantic_score`, `semantic_rank`, `keyword_score`, `keyword_rank`, `fused_score`, and `fused_rank`; `score` becomes the fused score. The diagnostic response must make the combined evidence understandable before generation. The final answer continues to cite only retrieved passages and uses the existing confidence/streaming behavior.

Require a small comparison: run one paraphrased question and one exact legal term or section-related question in semantic and hybrid modes, inspect the retrieved sources and answer, and document the observed difference without claiming a universal winner. Do not add re-ranking, evaluation harnesses, broad regression suites, GraphRAG, or agentic behavior. Update the architecture with the fusion choice and limitation. After creating the story, report its path only.
