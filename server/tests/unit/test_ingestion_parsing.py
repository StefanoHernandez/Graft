from pathlib import Path

import pytest

from graft.ingestion import parsing
from graft.ingestion.types import ParsedSection, ParseError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_plain_text():
    sections = parsing.parse_document("a.txt", "text/plain", b"hello")
    assert sections == [ParsedSection(text="hello")]


def test_parse_plain_text_keeps_utf8():
    sections = parsing.parse_document("notes.txt", "text/plain", _read("notes.txt"))
    assert "perché" in "\n".join(s.text for s in sections)


def test_parse_markdown_by_extension():
    sections = parsing.parse_document("a.md", "", b"# Title\n\nbody")
    assert [(s.heading, s.text) for s in sections] == [("Title", "body")]


def test_parse_markdown_splits_on_headings():
    sections = parsing.parse_document("guide.md", "text/markdown", _read("guide.md"))
    assert [s.heading for s in sections] == ["Installation", "Troubleshooting"]
    assert sections[1].text.strip() == "Restart the service."
    assert all(s.page is None for s in sections)


def test_parse_markdown_keeps_a_preamble_without_heading():
    sections = parsing.parse_document("a.md", "text/markdown", b"intro line\n\n# One\n\nbody")
    assert sections[0].heading is None
    assert sections[0].text.strip() == "intro line"


def test_parse_pdf_keeps_one_section_per_page():
    sections = parsing.parse_document("x.pdf", "application/pdf", _read("two_pages.pdf"))
    assert [(s.page, s.text.strip()) for s in sections] == [
        (1, "Alpha lives on page one."),
        (2, "Beta lives on page two."),
    ]


def test_parse_pdf_without_text_is_a_named_failure():
    with pytest.raises(ParseError) as excinfo:
        parsing.parse_document("scan.pdf", "application/pdf", _read("no_text.pdf"))
    assert excinfo.value.code == "no_extractable_text"


def test_parse_corrupt_pdf_is_a_named_failure():
    with pytest.raises(ParseError) as excinfo:
        parsing.parse_document("bad.pdf", "application/pdf", _read("corrupt.pdf"))
    assert excinfo.value.code in {"corrupt_document", "no_extractable_text"}


def test_parse_empty_text_is_a_named_failure():
    with pytest.raises(ParseError) as excinfo:
        parsing.parse_document("a.txt", "text/plain", b"   \n  ")
    assert excinfo.value.code == "no_extractable_text"


def test_parse_unsupported_raises():
    # Still a ValueError for callers that predate the coded errors.
    with pytest.raises(ValueError):
        parsing.parse_document("a.bin", "application/octet-stream", b"\x00\x01")


def test_page_limit_is_checked_before_extracting():
    with pytest.raises(ParseError) as excinfo:
        parsing.parse_document(
            "x.pdf", "application/pdf", _read("two_pages.pdf"), max_pages=1
        )
    assert excinfo.value.code == "too_many_pages"


def test_character_limit_stops_accumulation():
    with pytest.raises(ParseError) as excinfo:
        parsing.parse_document("a.txt", "text/plain", b"x" * 5000, max_chars=1000)
    assert excinfo.value.code == "too_much_text"
