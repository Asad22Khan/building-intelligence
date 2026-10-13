"""Pure chunking and embedding-input helpers (no network, no database)."""

import hashlib

from .mongodb_schema import CHUNK_OVERLAP, CHUNK_SIZE

_SEPARATORS = ("\n\n", "\n", ". ", "; ", " ")  # paragraph, line, sentence, clause, word


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split one section's text into chunks of about `size` characters with `overlap`.

    Prefers to cut at the coarsest separator found in the second half of the window.
    A text at or under `size` stays as one chunk.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in _SEPARATORS:
                idx = window.rfind(sep, size // 2)
                if idx != -1:
                    end = start + idx + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        gap = text.find(" ", start, start + 40)  # begin the overlap on a word boundary
        if gap != -1:
            start = gap + 1
    return chunks


def embedding_input(section: dict, chunk_text: str) -> str:
    """Text sent to Voyage: a short context line, then the chunk text."""
    number = section["section_id"].split(":", 1)[1].upper()
    return f"{section['act_label']}, Section {number}: {section['heading']}\n\n{chunk_text}"
