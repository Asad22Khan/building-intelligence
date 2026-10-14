# Story 3.2: Streamed Answers, Confidence and Open WebUI

## Purpose

Connect real RAG answer generation to the Open WebUI chat path that Story 1.1 established. Selecting **Building with RAG** with the `semantic` option in Open WebUI now runs the same retrieval, bounded context assembly, grounded generation, answer validation and citations that `POST /v1/query` runs, and streams the answer text to the chat as it is written.

Because Open WebUI cannot retract text that has already streamed, every answer is shown as a visible **draft** until its evidence check passes. The chat ends with a plain confidence and sources summary. `/v1/query` keeps the richer `QueryResult` for learning inspection.

This story extends Stories 1.1, 2.1–2.3 and 3.1; it does not replace them. Keep the shared registry and model IDs, the four endpoints, `QueryRequest`, `QueryResult`, `RetrievedChunk` and the nested `GenerationResult` (extended only additively, if at all), the Story 3.1 JSON output contract, context labels, outcomes and citation mapping, the Pipe's request shape, and the `.env.example` contract.

Out of scope: a second chat path, retrieval or context changes, streaming retrieval, new retrieval modes, agentic behavior, UI plugins or changes to the Open WebUI Pipe/Filter, multi-user authorization, an evaluation harness, and broad test suites.

## Prerequisites

- Stories 1.1 and 2.1–3.1 are complete: `uv sync` works, `uv run pytest` passes, Atlas data is loaded, and Story 3.1's `generate_answer: true` path answers on `/v1/query`.
- Open WebUI is already set up from the trainer's bundle (Story 1.1) and reachable at http://127.0.0.1:8080. Do not reinstall it, edit its admin panel, or change the Pipe or Filter.
- Read first: `docs/config.yaml` (absent: no configured project path), `docs/architecture.md`, Stories 1.1 and 2.1–3.1, `generation.py`, `patterns.py`, `contracts.py`, `app.py` (the chat adapter and `_stream`), `settings.py`, `tests/test_api.py`, `tests/test_generation.py`, and the Open WebUI bundle notes from Story 1.1 (the Pipe sends `rag-<pattern>`, `stream: true`, the latest user message and `rag_options`). Preserve existing work.
- Use only the existing settings with their names unchanged: `CAPSTONE_API_KEY`, `WEBUI_DEMO_CALLER_ID`, `GENERATION_API_BASE_URL`, `GENERATION_API_KEY`, `GENERATION_MODEL_NAME`. Rename or replace none and add none. Identity and generation settings stay server-side; the browser never supplies them.
- Never print, log, return, stream or commit credentials, the connection string or the generation key.

## Verification rule (read before doing anything)

**The coding assistant (Claude/Codex) must not use `curl` or any live HTTP or server call** (no `uvicorn`, no `Invoke-RestMethod`, no live provider, MongoDB or Voyage calls) in this story. It verifies only with the offline tests in this story and `uv run ruff check .`. The live smoke checks are run by the **participant directly in the Open WebUI interface** (not Postman, which would only repeat Story 3.1's checks). The assistant writes those checks as participant steps and reports them as **pending participant** in the handover. It never marks them passed.

All offline tests use a fake provider and a monkeypatched retrieval, and make no network or database call.

## Work to do

### 1. One generation operation, two surfaces

Keep one dispatch path. `/v1/query` and `/v1/chat/completions` both go through `run_pattern` for the selected pattern, and both consume the **same** generation/validation operation. Do not build a second chat path.

- Turn the Story 3.1 generation step into one operation that yields events: text pieces as the model writes, attempt and check markers, and finally one `QueryResult` with the nested `GenerationResult`. Retrieval and context assembly run first, non-streamed, and exactly once. Retrieval is never repeated for a retry.
- `/v1/query` (`generate_answer: true`) drains that operation and returns the final `QueryResult`. `/v1/chat/completions` renders the same events as the stream (or, when `stream` is false, as one message). The returned result and its stream must describe **one** operation. Two independent LLM calls for one request is a defect.
- The server sets `generate_answer` to true for chat (still never from the browser) and chat now calls retrieval through `run_pattern`; the `retrieve=False` placeholder shortcut goes away for `semantic`. The other five modes keep returning their honest `not_implemented` text, rendered through the same path.
- `generate_answer` false on `/v1/query` still behaves exactly as Story 2.3 and leaves `generation` empty.

### 2. Streaming the answer

Only answer writing streams.

- Call the proxy with the standard OpenAI chat-completions request and `stream: true` (`POST {GENERATION_API_BASE_URL}/chat/completions`, `Authorization: Bearer <GENERATION_API_KEY>`, `model` = `GENERATION_MODEL_NAME`). Keep the same timeout, low `temperature` and bounded `max_tokens` constants. No tool calls or provider-specific features. Use the HTTP client already in the project (`httpx`).
- The Story 3.1 JSON object is still what the model returns, with `answer` placed first. As provider deltas arrive, accumulate the full reply and forward only the decoded text of the `answer` value to the stream as it is completed, never the raw JSON braces, `outcome` or `claims`. If the provider does not stream, or the reply is not JSON, treat the whole reply as one piece to validate; never stream raw malformed output as an answer.
- Keep the provider call behind a small injectable seam (as Story 3.1's `post` was) so tests use a fake provider.
- Wire format: valid OpenAI-compatible SSE chunks (the existing `ChatCompletionChunk` models): a role chunk, content chunks, a final chunk with `finish_reason: "stop"`, then `data: [DONE]`. Keep `/v1/models` and mode selection unchanged.
- If the provider fails after text began (disconnect, timeout, error mid-stream), emit one clearly labelled line, for example `UNAVAILABLE — the answer was interrupted: <short reason>`, then still send the stop chunk and `[DONE]`. The stream is never left open.
- If the provider fails before any text, stream the Story 3.1 `unavailable` message as the whole reply and close normally. It carries no URL, key or stack trace.

### 3. Validation, drafts and bounded attempts

After each attempt finishes, validate it in code with no second LLM call. Use a small named constant for the maximum number of attempts (for example 2). This deliberately replaces Story 3.1's "one attempt" and nothing else.

A validated attempt: valid Story 3.1 JSON shape, `outcome` `answered`, a non-empty answer, at least one claim, every claim cites at least one supplied label, no unknown label, and each claim is supported by its cited passages by a simple, named, deterministic check (for example, enough of the claim's meaningful terms appear in its cited passage text). Keep this check small and its threshold a named constant. Each failed check yields a plain-language issue (for example "E3 is not a supplied passage", "claim 2 is not supported by E1").

Streaming happens before validation, so:

- Prefix the text of **every** attempt with a visible `DRAFT — checking evidence` line.
- If a check fails and attempts remain, stream a short retry line (for example `Check failed: <issue>. Trying again (attempt 2 of 2).`), then run the next attempt, again prefixed as a draft. The retry may add the previous issues to the prompt; it uses the same context and the same retrieved passages.
- After the final attempt, a failed check closes the chat text with `DRAFT — low confidence, not the final answer` plus a short reason. Never present the draft as validated.
- A validated attempt closes with the confidence and source summary below.
- Do not silently discard useful diagnostic checks, and never strip or repair an invalid citation to make it pass.

### 4. Result mapping (`QueryResult.generation`)

Use the Story 3.1 fields and outcomes, plus the confidence extension with its existing meanings:

| Situation | `outcome` | `confidence` | `answer` | `draft_answer` | `issues`, `attempts`, `low_confidence_reason` |
| --- | --- | --- | --- | --- | --- |
| An attempt validated | `answered` | high | the validated text | `None` | `issues` lists failed earlier checks (may be empty); `attempts` = number used |
| Final check failed, a draft existed | `malformed` | low | `None` | the last attempt's text | every failed check with its plain detail; `attempts`; a short `low_confidence_reason` |
| Model says the evidence is insufficient, or retrieval was `no_results` | `insufficient_evidence` | absent | `None` | `None` | as applicable; `no_results` makes no model call |
| No answer text can be judged (provider failure, empty or unusable reply) | `unavailable` or `malformed`, whichever is real | absent | `None` | any text that did stream, if any | the real failure |

- `confidence` is the existing float field. Define two named constants for high (validated) and low (failed check); the chat shows them as the words "high" and "low". `answer` is set **only** for a validated answer, as in Story 3.1.
- Every failed check from every attempt is stored in `issues` with its plain-language detail, not only the last one. `trace` keeps the steps (attempt number, check result, retry).
- `QueryResult.status` and the retrieval fields keep their Story 3.1 meaning. `message` is a short summary. Add no new top-level fields.

### 5. What Open WebUI shows

Keep the chat readable. In order:

1. Retrieval and context run silently (no streamed output yet).
2. The attempted answer streams under `DRAFT — checking evidence`.
3. On a retry, one line says the check failed and that another attempt is starting.
4. The close is one compact block in readable Markdown, for example:

```
✔ Evidence check passed. Confidence: high (attempt 1 of 2)
Sources:
- BNS_2023 §BNS-303 "Theft", p. 123 [E1]
- IPC_1860 §IPC-378 "Theft", p. 150 [E2]
```

or, after a failed final check:

```
DRAFT — low confidence, not the final answer
Reason: <short reason>. Checks that failed: <count> over <attempts> attempts.
```

For `insufficient_evidence` the chat says plainly that the supplied BNS and IPC documents do not support an answer, with no confidence line and no sources. For `unavailable` it says what to fix, with no secrets. Sources are the act-qualified section IDs, headings and pages resolved from the code's label map, never IDs the model invented. Keep the text plain; do not add a UI plugin or custom component.

`/v1/query` returns the full `QueryResult` (all `issues`, `trace`, `citations`, `supporting_passages`, `results`) for inspection.

### 6. Documentation

Update `docs/architecture.md` (keep it short) and the Open WebUI section of `README.md`. Cover: one generation operation feeding both `/v1/query` and chat, only answer writing streaming, the draft-then-validate display and why (streamed text cannot be retracted), the bounded attempts and what each field holds, the chat's closing block, the failure-mid-stream line, and that chat is no longer a placeholder for `semantic` (the other five modes still are). Replace the "chat is still a placeholder" notes. If `docs/manual-tests.md` lists chat placeholder expectations for `rag-semantic`, update those lines too.

## Completion checks

### Assistant-run (offline only)

1. `uv sync`, `uv run ruff check .` and `uv run pytest` pass.
2. Add and adapt only a few small tests (fake provider, monkeypatched retrieval). Update the existing `rag-semantic` chat tests in `tests/test_api.py` that expected the placeholder, and adapt Story 3.1's fake provider to the streaming seam, keeping their intent. Cover:
   - A good streamed reply: the SSE frames have a role chunk, content chunks, a `stop` chunk and `[DONE]`; the provider was called once; the streamed text matches the `answer` in the returned result (same operation); confidence is high; the closing block lists resolved sources.
   - A first attempt that fails the citation or support check and a second that passes: two provider calls, two draft prefixes, a retry line, `issues` holding the first failure, `attempts` = 2, confidence high.
   - Every attempt failing: the `DRAFT — low confidence, not the final answer` close, `outcome` `malformed`, `answer` `None`, `draft_answer` set, low confidence, every failed check in `issues`, and an invalid citation never stripped.
   - Provider failure after text began: the labelled unavailable line, then stop and `[DONE]`, and confidence absent.
   - `no_results` gives `insufficient_evidence` with no model call, and blank generation settings give `unavailable`.
   - `generate_answer` false on `/v1/query` still leaves `generation` empty; `/v1/models` still lists six IDs; a non-semantic model in chat still returns its `not_implemented` text.
3. No test or command run by the assistant touches the network, MongoDB, Voyage, the provider or a running server.

### Participant-run (pending participant)

The participant runs these in Open WebUI at http://127.0.0.1:8080 with the capstone API running, **Building with RAG** selected and **semantic** chosen in the RAG-options chip. Record the real result of each.

1. **Models and selection:** the six `rag-*` models still appear and the semantic option still selects. Expected: six models listed, semantic selectable.
2. **Supported answer:** ask "What is the punishment for theft?". Expected: text streams progressively under `DRAFT — checking evidence`, then a closing block with `Confidence: high`, attempts used (1 or 2), and at least one source with an act-qualified section ID and page. No spinner left hanging.
3. **Unsupported question:** ask "What is the penalty for a GDPR data breach?". Expected: a plain statement that the supplied documents do not support an answer; no confidence line, no sources, no invented citations.
4. **Failure is labelled:** stop the capstone API's generation by blanking `GENERATION_API_KEY` in `.env` and restarting the API (then restore it), and ask the theft question. Expected: an `unavailable` message telling you what to fix, with no key or URL shown, and the chat finishes cleanly.
5. **Stream shape:** in checks 2 to 4 the reply arrives in pieces, finishes without error, and the next question works in the same chat.
6. **Auth:** with `CAPSTONE_API_KEY` set in `.env` the way the bundle expects, chat still works. Note whether the API enforces the key today (as far as you can tell from behavior). Do not add enforcement in this story unless the bundle notes show the Pipe already sends it.
7. **Inspection:** `/v1/query` remains the place to see `issues`, `attempts` and `trace`; the chat shows only the compact summary.

Compact expected results for each check: outcome (`answered` / `insufficient_evidence` / `unavailable`), confidence (high / low / none), and source and attempt counts.

Do not build an evaluation harness, retries beyond the named bound, new retrieval modes, or broad testing.

## Handover

When finished, record:

- **Files created or changed.**
- **Constants chosen:** maximum attempts, high and low confidence values, the support-check threshold, and any changed token or timeout values.
- **How the single operation is shared** between `/v1/query` and chat, in two or three lines.
- **Commands actually run** (`uv sync`, `ruff`, `pytest`) and whether each passed.
- **Participant checks 1–7: pending participant.** Do not report them as run or passed by the assistant.
- **Open items:** anything skipped, flagged or uncertain (for example the support check's limits, or whether the Pipe sends `CAPSTONE_API_KEY`).

Later stories reuse this single generation/validation operation and its confidence fields for the remaining modes.
