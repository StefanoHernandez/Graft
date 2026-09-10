from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedSection:
    """A piece of a document that still knows where it came from.

    ``page`` is 1-based and only set for PDFs; ``heading`` is only set for
    Markdown. Provenance is what makes a citation checkable, so it travels with
    the text from the parser all the way into a chunk's metadata.
    """

    text: str
    page: int | None = None
    heading: str | None = None


@dataclass(frozen=True)
class ChunkDraft:
    content: str
    metadata: dict = field(default_factory=dict)


class ParseError(ValueError):
    """A document that cannot be ingested, named by a stable code.

    Subclasses ValueError so callers written against the old parser keep working.
    ``child_returncode`` is set when the failure came from the parser subprocess,
    and proves the child was reaped rather than left running.
    """

    def __init__(self, code: str, *, child_returncode: int | None = None):
        self.code = code
        self.child_returncode = child_returncode
        super().__init__(code)
