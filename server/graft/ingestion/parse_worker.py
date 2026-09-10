"""Run the document parser in a child process that can actually be killed.

pypdf is a pure-Python parser fed by files strangers upload. A pathological one
can spin far longer than any job should wait, and a thread cannot be stopped —
a timeout that leaves the work running is not a timeout. So parsing happens in a
subprocess the parent kills and reaps.

Child protocol: argv is `path filename mime`, and it always exits 0 after writing
one JSON object to stdout — `{"sections": [...]}` or `{"error": "<code>"}`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .parsing import MAX_CHARS, MAX_PAGES, parse_document
from .types import ParsedSection, ParseError

DEFAULT_TIMEOUT = 30.0


def _child_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("filename")
    parser.add_argument("mime")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS)
    # Test-only: makes the child slow on purpose so the timeout and cancellation
    # paths are exercised against a real process instead of a mock.
    parser.add_argument("--sleep", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = _child_arguments()
    if args.sleep:
        import time

        time.sleep(args.sleep)
    try:
        data = Path(args.path).read_bytes()
    except OSError:
        print(json.dumps({"error": "source_missing"}))
        return
    try:
        sections = parse_document(
            args.filename,
            args.mime,
            data,
            max_pages=args.max_pages,
            max_chars=args.max_chars,
        )
    except ParseError as exc:
        print(json.dumps({"error": exc.code}))
        return
    except Exception:  # noqa: BLE001 - the child must always answer with JSON
        print(json.dumps({"error": "corrupt_document"}))
        return
    print(
        json.dumps(
            {
                "sections": [
                    {"text": s.text, "page": s.page, "heading": s.heading} for s in sections
                ]
            }
        )
    )


async def parse_in_subprocess(
    path: Path,
    filename: str,
    mime_type: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_pages: int = MAX_PAGES,
    max_chars: int = MAX_CHARS,
    _debug_sleep: float = 0.0,
) -> list[ParsedSection]:
    argv = [
        sys.executable,
        "-m",
        "graft.ingestion.parse_worker",
        str(path),
        filename,
        mime_type or "",
        "--max-pages",
        str(max_pages),
        "--max-chars",
        str(max_chars),
    ]
    if _debug_sleep:
        argv += ["--sleep", str(_debug_sleep)]

    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        await _terminate(process)
        raise ParseError("parse_timeout", child_returncode=process.returncode) from None
    except asyncio.CancelledError:
        # A cancelled job must not leave a parser chewing through a file.
        await _terminate(process)
        raise

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError("parse_failed", child_returncode=process.returncode) from exc

    if "error" in payload:
        raise ParseError(payload["error"], child_returncode=process.returncode)
    return [
        ParsedSection(text=s["text"], page=s["page"], heading=s["heading"])
        for s in payload["sections"]
    ]


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.kill()
    await process.wait()


if __name__ == "__main__":
    main()
