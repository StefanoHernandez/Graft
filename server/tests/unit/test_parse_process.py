"""The parser runs in a killable child process.

pypdf is a pure-Python parser fed by strangers: a pathological file can spin far
longer than any request should. A thread cannot be stopped, so a timeout that
leaves the work running is not a timeout — hence a real subprocess.
"""
import asyncio
from pathlib import Path

import pytest

from graft.ingestion.parse_worker import parse_in_subprocess
from graft.ingestion.types import ParseError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


async def test_parses_a_real_pdf_out_of_process():
    sections = await parse_in_subprocess(
        FIXTURES / "two_pages.pdf", "two_pages.pdf", "application/pdf"
    )
    assert [(s.page, s.text.strip()) for s in sections] == [
        (1, "Alpha lives on page one."),
        (2, "Beta lives on page two."),
    ]


async def test_keeps_utf8_across_the_process_boundary():
    sections = await parse_in_subprocess(FIXTURES / "notes.txt", "notes.txt", "text/plain")
    assert "perché" in "\n".join(s.text for s in sections)


async def test_parse_failure_crosses_back_as_a_coded_error():
    with pytest.raises(ParseError) as excinfo:
        await parse_in_subprocess(FIXTURES / "no_text.pdf", "no_text.pdf", "application/pdf")
    assert excinfo.value.code == "no_extractable_text"


async def test_missing_file_is_a_coded_error():
    with pytest.raises(ParseError):
        await parse_in_subprocess(FIXTURES / "nope.pdf", "nope.pdf", "application/pdf")


async def test_timeout_kills_the_child(tmp_path):
    slow = tmp_path / "slow.txt"
    slow.write_text("x")
    with pytest.raises(ParseError) as excinfo:
        await parse_in_subprocess(
            slow, "slow.txt", "text/plain", timeout=0.5, _debug_sleep=30
        )
    assert excinfo.value.code == "parse_timeout"
    # The child is reaped, not left behind holding the file.
    assert excinfo.value.child_returncode is not None


async def test_cancellation_kills_the_child_and_propagates(tmp_path):
    slow = tmp_path / "slow.txt"
    slow.write_text("x")
    task = asyncio.create_task(
        parse_in_subprocess(slow, "slow.txt", "text/plain", timeout=30, _debug_sleep=30)
    )
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
