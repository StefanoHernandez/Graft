import pytest

from graft.ingestion import parsing


def test_parse_plain_text():
    assert parsing.parse_document("a.txt", "text/plain", b"hello") == "hello"


def test_parse_markdown_by_extension():
    assert parsing.parse_document("a.md", "", b"# Title\n\nbody") == "# Title\n\nbody"


def test_parse_pdf_joins_page_text(monkeypatch):
    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _Reader:
        def __init__(self, *args, **kwargs):
            self.pages = [_Page("Page one"), _Page("Page two")]

    monkeypatch.setattr(parsing, "PdfReader", _Reader)
    assert parsing.parse_document("x.pdf", "application/pdf", b"%PDF-fake") == "Page one\nPage two"


def test_parse_unsupported_raises():
    with pytest.raises(ValueError):
        parsing.parse_document("a.bin", "application/octet-stream", b"\x00\x01")
