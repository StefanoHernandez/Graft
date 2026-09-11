from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader

from .types import ParsedSection, ParseError

_TEXT_MIME = {"text/plain", "text/markdown"}
_TEXT_EXT = (".txt", ".md", ".markdown")
_MARKDOWN_EXT = (".md", ".markdown")

MAX_PAGES = 200
MAX_CHARS = 1_000_000

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")


def _pdf_sections(data: bytes, max_pages: int, max_chars: int) -> list[ParsedSection]:
    try:
        reader = PdfReader(BytesIO(data))
        pages = reader.pages
        page_count = len(pages)
    except Exception as exc:
        raise ParseError("corrupt_document") from exc

    # Checked before extraction: refusing a 5000-page book must not cost the time
    # of extracting it first.
    if page_count > max_pages:
        raise ParseError("too_many_pages")

    sections: list[ParsedSection] = []
    total = 0
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ParseError("corrupt_document") from exc
        if not text.strip():
            continue
        total += len(text)
        if total > max_chars:
            raise ParseError("too_much_text")
        sections.append(ParsedSection(text=text, page=number))
    return sections


def _markdown_sections(text: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        joined = "\n".join(body).strip()
        if joined:
            sections.append(ParsedSection(text=joined, heading=heading))
        body.clear()

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            heading = match.group(1)
        else:
            body.append(line)
    flush()
    return sections


def parse_document(
    filename: str,
    mime_type: str,
    data: bytes,
    *,
    max_pages: int = MAX_PAGES,
    max_chars: int = MAX_CHARS,
) -> list[ParsedSection]:
    """Extract a document as sections that carry their provenance.

    Raises ParseError with a stable code; an empty result is always an error,
    because a document that produced no text is a failed ingestion, not a
    document that is ready with zero chunks.
    """
    name = filename.lower()
    if mime_type == "application/pdf" or name.endswith(".pdf"):
        sections = _pdf_sections(data, max_pages, max_chars)
    elif mime_type in _TEXT_MIME or name.endswith(_TEXT_EXT):
        text = data.decode("utf-8", errors="replace")
        if len(text) > max_chars:
            raise ParseError("too_much_text")
        if mime_type == "text/markdown" or name.endswith(_MARKDOWN_EXT):
            sections = _markdown_sections(text)
        else:
            stripped = text.strip()
            sections = [ParsedSection(text=stripped)] if stripped else []
    else:
        raise ParseError("unsupported_type")

    if not sections:
        raise ParseError("no_extractable_text")
    return sections
