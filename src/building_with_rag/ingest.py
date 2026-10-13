"""Turn the supplied BNS and IPC PDFs into section-level JSONL corpora.

Run: uv run python -m building_with_rag.ingest

Reads data/raw/*.pdf (never modified) and writes data/processed/{bns,ipc}_sections.jsonl.
No network, API or database access.

The two PDFs are laid out differently:
- BNS: an index and a BNS-to-IPC correspondence table come first; the Act text starts later.
  Each section's heading is printed on the line *before* its number ("heading before").
- IPC: each section is printed as "N. Heading.--text" ("inline"), preceded by a margin copy
  of the number and heading, and each page ends with footnotes.
"""

import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pypdf

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"
PROVENANCE = RAW_DIR / "PROVENANCE.md"

PARSER = "pypdf"
PARSER_VERSION = pypdf.__version__

Line = tuple[int, str]  # (1-based page number, text)


@dataclass(frozen=True)
class ActConfig:
    key: str  # "bns" / "ipc": file prefix and section_id prefix
    act: str
    act_label: str
    status: str
    pdf: str
    status_version: str  # taken from data/raw/PROVENANCE.md notes
    total_sections: int  # base section numbers expected (used only to report gaps)
    heading_style: str  # "before" (heading on the line before) or "inline" (N. Heading.--text)
    body_marker: str | None = None  # regex of the first body line; skips the index before it

    @property
    def out_path(self) -> Path:
        return OUT_DIR / f"{self.key}_sections.jsonl"


BNS = ActConfig(
    key="bns",
    act="BNS_2023",
    act_label="Bharatiya Nyaya Sanhita, 2023",
    status="in_force",
    pdf="BNS_2023_bare_act.pdf",
    status_version="Act No. 45 of 2023; in force from 1 July 2024 (per PROVENANCE.md)",
    total_sections=358,
    heading_style="before",
    body_marker=r"^1\. \(1\) This Act may be called the Bharatiya",
)
IPC = ActConfig(
    key="ipc",
    act="IPC_1860",
    act_label="Indian Penal Code, 1860",
    status="repealed",
    pdf="IPC_1860_bare_act.pdf",
    status_version="Act No. 45 of 1860; repealed 1 July 2024 (per PROVENANCE.md)",
    total_sections=511,
    heading_style="inline",
)

# An optional "8*[" prefix marks an amended section in the IPC text.
START = re.compile(r"^(?:\d+\*\[?)?(\d{1,3})([A-Z]{0,2})\.\s*(\S.*)$")
INLINE_START = re.compile(
    r"^(?:\d+\*\[?)?(\d{1,3})([A-Z]{0,2})\.\s+(.{3,250}?)(?:[.;:]\s?(?:-\s?-|-|—|–)|\s?(?:--|—|–))\s*(.*)$"
)
# Repealed sections are printed as: N. [Heading.] Rep. by ...
REPEALED_START = re.compile(r"^(?:\d+\*\[?)?(\d{1,3})([A-Z]{0,2})\.\s*\[?(.{3,250}?)\.?\]\s*(.*)$")
CHAPTER = re.compile(r"^CHAPTER\s+([IVXL]+[A-Z]?)\b\.?\s*(.*)$")
JUNK_LINE = re.compile(r"^(?:[—–-]{5,}|Note: For Reference only\.?|HomePage)$")
PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}$", re.IGNORECASE)
STANDALONE_NUMBER = re.compile(r"^\d{1,3}[A-Z]{0,2}\.\s*$")
MISSING_DOT = re.compile(r'^(\d+\*\[\d{1,3}[A-Z]{0,2})(\s+")')
REPEALED_TAIL = re.compile(r"\]\s*(Rep|Omitted)")
# A run of repealed sections is printed as one note: "161 to 165A. Rep. by ..."
RANGE_START = re.compile(r"^(\d{1,3})([A-Z]{0,2}) to (\d{1,3})([A-Z]{0,2})\.")
STANDALONE_RANGE = re.compile(r"^\d{1,3}[A-Z]{0,2} to \d{1,3}[A-Z]{0,2}\.\s*$")
REVIEW_MARK = "\x00"  # prefix set by clean_ipc on a line whose printed number was corrected
RULE_LINE = re.compile(r"^-{10,}$")
NEW_PARAGRAPH = re.compile(r"^(\(|Illustration|Explanation|Exception|Provided)")


@dataclass
class Section:
    number: int
    suffix: str
    chapter: str
    chapter_title: str
    heading: str
    lines: list[Line] = field(default_factory=list)
    review: bool = False

    @property
    def text(self) -> str:
        out = ""
        for _, line in self.lines:
            if not out:
                out = line
            elif NEW_PARAGRAPH.match(line):
                out += "\n" + line
            else:
                out += " " + line
        return out.strip()


# ---------------------------------------------------------------- reading the PDF


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance_sha(pdf_name: str) -> str | None:
    for row in PROVENANCE.read_text(encoding="utf-8").splitlines():
        if pdf_name in row:
            found = re.search(r"\b[0-9a-f]{64}\b", row)
            if found:
                return found.group(0)
    return None


def read_pages(path: Path) -> tuple[list[list[str]], list[int]]:
    """Return per-page cleaned lines and the 1-based numbers of pages with no text."""
    reader = pypdf.PdfReader(str(path))
    pages: list[list[str]] = []
    empty: list[int] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").replace("\xa0", " ")
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            empty.append(number)
        pages.append(lines)
    return pages, empty


def drop_repeated(pages: list[list[str]]) -> list[Line]:
    """Remove page numbers and running headers/footers; flatten to (page, line)."""
    seen: Counter[str] = Counter()
    for lines in pages:
        seen.update(set(lines))
    threshold = max(3, int(len(pages) * 0.3))
    repeated = {ln for ln, n in seen.items() if n >= threshold and len(ln) >= 6}
    flat: list[Line] = []
    for number, lines in enumerate(pages, start=1):
        for ln in lines:
            if ln in repeated or PAGE_NUMBER.match(ln) or JUNK_LINE.match(ln):
                continue
            flat.append((number, ln))
    return flat


def inline_start(lines: list[Line], i: int) -> tuple[re.Match[str], int] | None:
    """Match "N. Heading.--text" at line i; the heading may wrap onto up to 2 more lines."""
    text = lines[i][1].lstrip(REVIEW_MARK)
    for extra in range(3):
        found = INLINE_START.match(text) or REPEALED_START.match(text)
        if found:
            return found, extra
        if i + 1 + extra >= len(lines):
            break
        text += " " + lines[i + 1 + extra][1]
    return None


def clean_ipc(flat: list[Line]) -> list[Line]:
    """Drop IPC margin numbers, rule lines and footnote entries.

    A numbered line that is not a section start begins a footnote entry; the entry runs
    until a line ending in a full stop. Entries can spill onto the top of the next page.
    """
    # A repealed section is a margin number followed by "[Heading.] Rep. by ..."; join them.
    joined: list[Line] = []
    i = 0
    while i < len(flat):
        if (
            STANDALONE_NUMBER.match(flat[i][1])
            and i + 1 < len(flat)
            and (flat[i + 1][1].startswith("[") or REPEALED_TAIL.search(flat[i + 1][1]))
        ):
            joined.append((flat[i + 1][0], f"{flat[i][1].strip()} {flat[i + 1][1]}"))
            i += 2
        else:
            page, line = flat[i]
            joined.append((page, MISSING_DOT.sub(r"\1.\2", line)))
            i += 1
    flat = joined

    cleaned: list[Line] = []
    in_footnote = False
    margin = ""  # the margin copy of the number just before a section, e.g. "330"
    margin_age = 0
    for i, (page, line) in enumerate(flat):
        if STANDALONE_NUMBER.match(line):
            margin, margin_age = line.strip().rstrip("."), 0
            continue
        if STANDALONE_RANGE.match(line) or RULE_LINE.match(line):
            continue
        if not in_footnote and START.match(line) and inline_start(flat, i) is None:
            in_footnote = True
        if in_footnote:
            nxt = flat[i + 1][1] if i + 1 < len(flat) else ""
            if re.search(r"[.\]]\"?$", line) and not nxt.startswith("("):
                in_footnote = False
            continue
        margin_age += 1
        if margin and margin_age <= 4 and inline_start(flat, i) is not None:
            printed = START.match(line)
            if printed and printed.group(1) + printed.group(2) != margin:
                # The source prints two different numbers; trust the margin and flag it.
                line = REVIEW_MARK + re.sub(
                    r"^((?:\d+\*\[?)?)\d{1,3}[A-Z]{0,2}\.", rf"\g<1>{margin}.", line
                )
            margin = ""
        cleaned.append((page, line))
    return cleaned


def clean_lines(flat: list[Line], cfg: ActConfig) -> list[Line]:
    return clean_ipc(flat) if cfg.heading_style == "inline" else flat


# ---------------------------------------------------------------- section parsing


def _is_next(last: tuple[int, str], number: int, suffix: str) -> bool:
    last_number, last_suffix = last
    if suffix == "":
        return number == last_number + 1
    return number == last_number and suffix > last_suffix


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


def _pop_margin_copy(lines: list[Line], heading: str) -> None:
    """IPC prints the heading in the margin before the section; remove that duplicate."""
    target = _norm(heading)
    for k in (1, 2, 3, 4):
        if len(lines) >= k and _norm("".join(t for _, t in lines[-k:])).startswith(target):
            del lines[-k:]
            return


def _take_heading(lines: list[Line]) -> tuple[str, bool]:
    """Pop a heading printed on the line(s) before a section number. Returns (heading, ok)."""
    if not lines:
        return "", False
    ok = len(lines[-1][1]) <= 150
    parts = [lines.pop()[1]]
    while lines and len(parts) < 2 and len(lines[-1][1]) <= 100:
        if re.search(r"[.,;:—)]$", lines[-1][1]):
            break
        parts.insert(0, lines.pop()[1])
    return " ".join(parts).rstrip(".").strip(), ok


def _from_body(flat: list[Line], cfg: ActConfig) -> list[Line]:
    """Skip the index that precedes the Act text, if the act has one."""
    if not cfg.body_marker:
        return flat
    marker = re.compile(cfg.body_marker)
    for i, (_, line) in enumerate(flat):
        if marker.match(line):
            for j in range(i, max(i - 8, -1), -1):
                if CHAPTER.match(flat[j][1]):
                    return flat[j:]
            return flat[i:]
    return flat


def parse_sections(flat: list[Line], cfg: ActConfig) -> list[Section]:
    """Split flattened lines into sections.

    A line starts a section only if its number is the next expected one, so numbered
    sub-clauses, footnotes and table rows inside the text are not mistaken for sections.
    """
    flat = _from_body(flat, cfg)
    sections: list[Section] = []
    preamble: list[Line] = []
    chapter = chapter_title = ""
    last = (0, "")
    i = 0
    while i < len(flat):
        page, line = flat[i]
        corrected = line.startswith(REVIEW_MARK)
        line = line.lstrip(REVIEW_MARK)

        chap = CHAPTER.match(line)
        if chap and (not chap.group(2) or chap.group(2).isupper()):
            chapter, chapter_title = chap.group(1), chap.group(2).strip()
            i += 1
            title_lines: list[str] = []
            while (
                i < len(flat)
                and len(title_lines) < 3
                and flat[i][1].isupper()
                and not START.match(flat[i][1])
                and not CHAPTER.match(flat[i][1])
            ):
                title_lines.append(flat[i][1])
                i += 1
            if title_lines:
                chapter_title = " ".join(([chapter_title] if chapter_title else []) + title_lines)
            continue

        rng = RANGE_START.match(line) if cfg.heading_style == "inline" else None
        if rng and _is_next(last, int(rng.group(1)), rng.group(2)):
            # No per-section text exists for these; skip the note, keep the numbering going.
            last = (int(rng.group(3)), rng.group(4))
            end = i
            while end < len(flat) - 1 and not flat[end][1].endswith("."):
                end += 1
            i = end + 1
            continue

        start = START.match(line)
        if start and _is_next(last, int(start.group(1)), start.group(2)):
            number, suffix = int(start.group(1)), start.group(2)
            holder = sections[-1].lines if sections else preamble
            consumed = 0
            if cfg.heading_style == "inline":
                hit = inline_start(flat, i)
                if hit:
                    found, extra = hit
                    heading, first_text = found.group(3).strip(), found.group(4).strip()
                    _pop_margin_copy(holder, heading)
                    review, consumed = suffix != "" or corrected, 1 + extra
            else:
                heading, ok = _take_heading(holder)
                first_text = start.group(3)
                review, consumed = suffix != "" or not ok, 1
            if consumed:
                if not chapter or not chapter_title or not heading:
                    review = True
                section = Section(number, suffix, chapter, chapter_title, heading, review=review)
                if first_text:
                    section.lines.append((page, first_text))
                sections.append(section)
                last = (number, suffix)
                i += consumed
                continue

        (sections[-1].lines if sections else preamble).append((page, line))
        i += 1

    if sections and sections[-1].number == cfg.total_sections:
        sections[-1].review = True  # may run on into trailing material
    for section in sections:
        if not section.text:
            section.review = True
    return sections


# ---------------------------------------------------------------- output


def to_record(section: Section, cfg: ActConfig, sha: str) -> dict:
    pages = [p for p, _ in section.lines]
    return {
        "section_id": f"{cfg.key}:{section.number}{section.suffix}",
        "act": cfg.act,
        "act_label": cfg.act_label,
        "status": cfg.status,
        "chapter": section.chapter,
        "chapter_title": section.chapter_title,
        "section_number": section.number,
        "heading": section.heading,
        "text": section.text,
        "source_pdf": cfg.pdf,
        "source_sha256": sha,
        "parser": PARSER,
        "parser_version": PARSER_VERSION,
        "source_status_version": cfg.status_version,
        "needs_review": section.review,
        "page_start": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
    }


def is_current(path: Path, sha: str) -> bool:
    """True if the file already holds records made from this exact PDF and parser."""
    if not path.exists():
        return False
    try:
        with path.open(encoding="utf-8") as f:
            records = [json.loads(ln) for ln in f if ln.strip()]
    except ValueError:
        return False
    return bool(records) and all(
        r.get("source_sha256") == sha and r.get("parser_version") == PARSER_VERSION for r in records
    )


def write_atomically(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def ingest(cfg: ActConfig, force: bool = False) -> int:
    pdf = RAW_DIR / cfg.pdf
    if not pdf.exists():
        print(f"[{cfg.key}] MISSING INPUT: {pdf}", file=sys.stderr)
        return 1
    sha = sha256_of(pdf)
    expected = provenance_sha(cfg.pdf)
    if expected is None:
        print(f"[{cfg.key}] no SHA-256 for {cfg.pdf} in PROVENANCE.md", file=sys.stderr)
        return 1
    if sha != expected:
        print(
            f"[{cfg.key}] SHA-256 MISMATCH for {cfg.pdf}: file {sha}, PROVENANCE.md {expected}",
            file=sys.stderr,
        )
        return 1
    if not force and is_current(cfg.out_path, sha):
        print(f"[{cfg.key}] {cfg.out_path.name} already current for this PDF; left unchanged")
        return 0

    pages, empty_pages = read_pages(pdf)
    flat = clean_lines(drop_repeated(pages), cfg)
    sections = parse_sections(flat, cfg)
    records = [to_record(s, cfg, sha) for s in sections]
    if not records:
        print(f"[{cfg.key}] no sections found; nothing written", file=sys.stderr)
        return 1
    write_atomically(cfg.out_path, records)

    found = {s.number for s in sections}
    missing = [n for n in range(1, cfg.total_sections + 1) if n not in found]
    flagged = sum(1 for s in sections if s.review)
    print(f"[{cfg.key}] wrote {len(records)} records to {cfg.out_path}")
    print(f"[{cfg.key}] needs_review: {flagged}; pages with no text: {empty_pages or 'none'}")
    shown = f"{missing[:40]}{' ...' if len(missing) > 40 else ''}" if missing else "none"
    print(f"[{cfg.key}] section numbers not found (of 1..{cfg.total_sections}): {shown}")
    return 0


def main() -> int:
    force = "--force" in sys.argv[1:]
    codes = [ingest(cfg, force) for cfg in (BNS, IPC)]
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main())
