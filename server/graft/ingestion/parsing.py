from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

_TEXT_MIME = {"text/plain", "text/markdown"}
_TEXT_EXT = (".txt", ".md", ".markdown")


def parse_document(filename: str, mime_type: str, data: bytes) -> str:
    name = filename.lower()
    if mime_type == "application/pdf" or name.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if mime_type in _TEXT_MIME or name.endswith(_TEXT_EXT):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported document type: {mime_type or filename!r}")
