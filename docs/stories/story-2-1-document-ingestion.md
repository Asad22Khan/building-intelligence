# Story 2.1: Document Ingestion

## Purpose

Turn the supplied BNS and IPC PDFs into a small, inspectable, section-level corpus: one JSONL record per section, written to `data/processed/`. This story extends the Story 1.1 application; it does not replace it.

Out of scope: MongoDB, embeddings, vector indexes, retrieval, answer generation, chunking, and any change to the API endpoints. Those belong to later stories.

## Prerequisites

- Story 1.1 is complete (`uv sync` works, `uv run pytest` passes).
- Supplied inputs exist and are never modified:
  - `data/raw/BNS_2023_bare_act.pdf`
  - `data/raw/IPC_1860_bare_act.pdf`
  - `data/raw/PROVENANCE.md` (source URLs, retrieval date, SHA-256 of each PDF)
- If any input is missing, or a PDF's SHA-256 does not match `PROVENANCE.md`, stop and report it exactly. Do not guess or download replacements.
- Read first: `docs/config.yaml` (absent: no configured project path), `docs/architecture.md`, the Story 1.1 file, existing code under `src/building_with_rag/`, and `data/raw/`. Preserve existing work.
- Reuse the existing `.env.example` contract. Do not add or rename settings. No credentials are needed.

## Work to do

### 1. Parser dependency

Choose a suitable PDF text-extraction library and add it with UV (`uv add ...`). Prefer one that gives page-level text with reliable ordering. Record the choice and its version (it becomes `parser` and `parser_version` in each record).

### 2. Ingestion command

Add a small module, for example `src/building_with_rag/ingest.py`, run as a command such as `uv run python -m building_with_rag.ingest`. It reads the two PDFs and writes:

- `data/processed/bns_sections.jsonl`
- `data/processed/ipc_sections.jsonl`

Keep BNS and IPC records in separate files, even where section numbers match. Do not call the API, MongoDB, or any network service.

### 3. Record format

One JSON object per line, UTF-8, with exactly these required fields:

| Field | Value |
| --- | --- |
| `section_id` | `bns:<number>` or `ipc:<number>` |
| `act` | `BNS_2023` or `IPC_1860` |
| `act_label` | human-readable act name, taken from the source |
| `status` | `in_force` (BNS) or `repealed` (IPC) |
| `chapter` | string, for example `I` |
| `chapter_title` | chapter title as printed in the source |
| `section_number` | integer |
| `heading` | section heading as printed |
| `text` | section text |
| `source_pdf` | PDF file name |
| `source_sha256` | SHA-256 of that PDF |
| `parser` | parser library name |
| `parser_version` | parser library version |
| `source_status_version` | status or version information taken from `PROVENANCE.md` / the source; do not invent it |
| `needs_review` | `true` when extraction was uncertain, otherwise `false` |

Page references (for example `page_start`, `page_end`) may be kept as additional fields. They do not replace any field above. Do not invent unknown provenance: if a value is not in the source or `PROVENANCE.md`, leave it out of the claim and set `needs_review` to `true`.

### 4. Extraction rules

- Extract sections without rewriting their meaning. Only normalize whitespace and remove repeated page headers/footers and obvious duplicate extraction.
- Handle sections that span pages by joining their text in order.
- The BNS PDF also contains an index and a BNS-to-IPC correspondence table. They are context, not sections: do not emit them as section records.
- Be conservative. If a page looks scanned, has no extractable text, or a section boundary is unclear, flag the affected records `needs_review: true` and report them. Do not silently repair.

### 5. Safe re-runs

- Write output to a temporary file and replace the target as one step, so a failed run never leaves a half-written corpus.
- Re-running must not append duplicates: each run rewrites the whole file.
- Do not overwrite a supplied valid corpus unnecessarily: if the existing file's records already carry the current `source_sha256`, leave it as is.
- If a source hash has changed, regenerate the whole file as one replacement. Never mix records from different source versions.

### 6. Architecture notes

Update `docs/architecture.md` (keep it short) with: the parser choice and version, the output format and file locations, the run command, and known limitations.

## Completion checks

Keep these small. Run each and record the real result.

1. `uv sync` and `uv run ruff check .` pass; `uv run pytest` still passes.
2. `uv run python -m building_with_rag.ingest` writes both JSONL files.
3. Inspect a few representative records in each file against the PDF, including one section that spans pages if present.
4. Every record has all required fields with the exact values above; no record has empty `text`.
5. Run the command a second time: the files are unchanged and contain no duplicate `section_id`.
6. `data/raw/` files are unchanged (hashes still match `PROVENANCE.md`).

Do not build a corpus-validation framework, a reference-difference report, broad security tests, or synthetic permission records.

## Handover

Record when finished:

- **Inputs:** the two PDFs and `PROVENANCE.md` named above.
- **Outputs:** `data/processed/bns_sections.jsonl` and `data/processed/ipc_sections.jsonl`, with record counts and how many have `needs_review: true`.
- **How later chunking keeps provenance:** each chunk will carry its parent `section_id`, `act`, and `source_pdf` / `source_sha256` (plus page references if kept), so every retrieved passage traces back to its section and source.
- **Commands actually run** and whether each passed.
- **Open items:** anything skipped or flagged, and why.

### Handover record

- **Inputs:** `data/raw/BNS_2023_bare_act.pdf`, `data/raw/IPC_1860_bare_act.pdf`, `data/raw/PROVENANCE.md`. Both PDF hashes match `PROVENANCE.md` and the files are unchanged.
- **Files created or changed:** `src/building_with_rag/ingest.py`, `tests/test_ingest.py`, `pyproject.toml` (added `pypdf>=5.0`), `uv.lock`, `docs/architecture.md`.
- **Outputs:**
  - `data/processed/bns_sections.jsonl`: 358 records (sections 1-358, none missing), 1 `needs_review` (`bns:358`, may run into trailing material).
  - `data/processed/ipc_sections.jsonl`: 550 records (every number 1-511 except 161-165, plus lettered sections such as 52A), 46 `needs_review`.
- **Commands actually run** (via `python -m uv`): `uv sync` passed; `uv run ruff check .` passed; `uv run pytest` passed (13 tests); `uv run python -m building_with_rag.ingest` wrote both files; a second run reported both files "already current" and the file hashes were identical before and after.
- **Checks done:** all required fields present on every record; no duplicate `section_id`; no empty `text`, `heading`, `chapter` or `chapter_title`; `section_number` is an int and `chapter` a string; `act`/`status` values as specified. Spot-checked `bns:1`, `bns:103`, `bns:2` (spans pages 75-81), `ipc:1`, `ipc:4` (spans pages 2-3), `ipc:302` and `ipc:479` against the extracted PDF text. The check ran against the extracted text, not by eye on the PDF pages.
- **How later chunking keeps provenance:** each chunk will carry its parent `section_id`, `act`, `source_pdf` / `source_sha256` and the `page_start` / `page_end` range, so every retrieved passage traces back to its section and source.
- **Open items:**
  - IPC sections 161-165 are repealed together in one note ("161 to 165A. Rep. by ..."), so no records exist for them. They are not invented.
  - One source typo: the IPC margin prints 330 but the section body prints 320. The margin number is used and the record is flagged `needs_review`.
  - Lettered IPC sections (for example 52A) use `section_id` `ipc:52A` with `section_number` 52, so ids stay unique; they are flagged `needs_review`.
  - Text keeps the PDF's own noise (for example "t he" split words, IPC footnote markers like `1*[...]`). It is not repaired.
  - A few unnumbered footnote continuation lines in the IPC may still sit inside a section's text.
  - Headings and chapter titles come from the PDF layout; a heading that wraps over lines or follows a sub-heading may be slightly off.
