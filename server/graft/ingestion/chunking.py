from __future__ import annotations

import re

from .types import ChunkDraft, ParsedSection, ParseError

MAX_CHUNKS = 2000

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _windows(text: str, size: int, step: int) -> list[str]:
    """Last resort for a paragraph longer than a whole chunk."""
    pieces = []
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            pieces.append(piece)
    return pieces


def chunk_sections(
    sections: list[ParsedSection],
    *,
    size: int = 1000,
    overlap: int = 200,
    max_chunks: int = MAX_CHUNKS,
) -> list[ChunkDraft]:
    """Pack paragraphs into chunks without crossing a section boundary.

    Two pages are never merged into one chunk: a citation that points at a page
    has to be true. Within a section, whole paragraphs are packed up to `size`
    and the last `overlap` characters are repeated at the start of the next
    chunk, so a sentence split across the seam is still retrievable. A single
    paragraph longer than `size` falls back to fixed windows.

    This is a measurable baseline, not a layout-aware parser: it makes no promise
    about tables, columns or OCR.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")

    step = size - overlap
    drafts: list[ChunkDraft] = []

    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        metadata = {}
        if section.page is not None:
            metadata["page"] = section.page
        if section.heading is not None:
            metadata["heading"] = section.heading

        def emit(content: str, metadata: dict = metadata) -> None:
            content = content.strip()
            if not content:
                return
            drafts.append(ChunkDraft(content=content, metadata=dict(metadata)))
            if len(drafts) > max_chunks:
                raise ParseError("too_many_chunks")

        current = ""
        for paragraph in (p.strip() for p in _PARAGRAPH_BREAK.split(text)):
            if not paragraph:
                continue
            if len(paragraph) > size:
                if current:
                    emit(current)
                    current = ""
                for window in _windows(paragraph, size, step):
                    emit(window)
                continue
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= size:
                current = candidate
                continue
            emit(current)
            tail = current[-overlap:] if overlap else ""
            with_tail = f"{tail}\n\n{paragraph}" if tail else paragraph
            current = with_tail if len(with_tail) <= size else paragraph
        if current:
            emit(current)

    return drafts
