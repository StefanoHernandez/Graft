import pytest

from graft.ingestion.chunking import chunk_sections
from graft.ingestion.types import ParsedSection, ParseError


def _section(text, page=None, heading=None):
    return ParsedSection(text=text, page=page, heading=heading)


def test_empty_returns_no_chunks():
    assert chunk_sections([_section("   \n  ")]) == []


def test_short_text_single_chunk():
    chunks = chunk_sections([_section("hello world")], size=1000, overlap=200)
    assert [c.content for c in chunks] == ["hello world"]


def test_metadata_carries_page_and_heading():
    chunks = chunk_sections([_section("body text", page=3, heading="Setup")])
    assert chunks[0].metadata == {"page": 3, "heading": "Setup"}


def test_metadata_omits_what_the_parser_could_not_know():
    assert chunk_sections([_section("body text")])[0].metadata == {}


def test_pages_are_never_merged_into_one_chunk():
    chunks = chunk_sections(
        [_section("Alpha.", page=1), _section("Beta.", page=2)], size=1000, overlap=100
    )
    assert [(c.content, c.metadata["page"]) for c in chunks] == [("Alpha.", 1), ("Beta.", 2)]


def test_paragraphs_are_packed_up_to_the_cap():
    paragraphs = "\n\n".join(f"Paragraph {i} " + "w" * 90 for i in range(6))
    chunks = chunk_sections([_section(paragraphs)], size=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.content) <= 300 for c in chunks)
    # A paragraph that fits inside a chunk is never cut in the middle.
    joined = "\n".join(c.content for c in chunks)
    for i in range(6):
        assert f"Paragraph {i} " + "w" * 90 in joined


def test_overlap_repeats_the_tail_of_the_previous_chunk():
    paragraphs = "\n\n".join("x" * 80 for _ in range(6))
    chunks = chunk_sections([_section(paragraphs)], size=200, overlap=40)
    assert len(chunks) > 1
    assert chunks[0].content[-40:] in chunks[1].content


def test_a_single_long_paragraph_falls_back_to_windows():
    chunks = chunk_sections([_section("a" * 2500)], size=1000, overlap=200)
    assert len(chunks) == 4
    assert all(len(c.content) <= 1000 for c in chunks)
    assert chunks[0].content[-200:] == chunks[1].content[:200]


def test_no_words_are_lost():
    words = [f"w{i}" for i in range(400)]
    section = _section("\n\n".join(" ".join(words[i:i + 8]) for i in range(0, 400, 8)))
    produced = " ".join(c.content for c in chunk_sections([section], size=200, overlap=50))
    seen = set(produced.split())
    assert set(words) <= seen


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        chunk_sections([_section("x")], size=0)
    with pytest.raises(ValueError):
        chunk_sections([_section("x")], size=100, overlap=100)


def test_chunk_ceiling_is_enforced_before_embedding():
    section = _section("\n\n".join("word " * 20 for _ in range(200)))
    with pytest.raises(ParseError) as excinfo:
        chunk_sections([section], size=100, overlap=0, max_chunks=5)
    assert excinfo.value.code == "too_many_chunks"
