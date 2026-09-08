import pytest

from graft.ingestion.chunking import chunk_text


def test_empty_returns_no_chunks():
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk():
    assert chunk_text("hello world", size=1000, overlap=200) == ["hello world"]


def test_splits_with_overlap():
    text = "abcdefghij" * 300  # 3000 chars
    chunks = chunk_text(text, size=1000, overlap=200)
    # step = 800 -> starts at 0, 800, 1600, 2400 -> 4 chunks
    assert len(chunks) == 4
    assert all(len(c) <= 1000 for c in chunks)
    # overlap: end of chunk 0 reappears at start of chunk 1
    assert chunks[0][-200:] == chunks[1][:200]


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        chunk_text("x", size=0)
    with pytest.raises(ValueError):
        chunk_text("x", size=100, overlap=100)
