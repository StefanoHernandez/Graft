"""Regenerate the PDF fixtures: `uv run python tests/fixtures/documents/make_fixtures.py`.

Handwritten so the fixtures are real PDFs parsed by the real pypdf, with no extra
dependency and no binary blob nobody can explain. Keep them tiny and readable.
"""
from pathlib import Path

HERE = Path(__file__).parent


def _pdf(objects: list[bytes]) -> bytes:
    """Assemble numbered objects into a PDF with a correct xref table."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<</Size %d /Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


def _content(text: str) -> bytes:
    stream = b"BT /F1 12 Tf 20 150 Td (%s) Tj ET" % text.encode("ascii")
    return b"<</Length %d>>\nstream\n%s\nendstream" % (len(stream), stream)


def two_pages() -> bytes:
    return _pdf([
        b"<</Type /Catalog /Pages 2 0 R>>",
        b"<</Type /Pages /Kids [3 0 R 5 0 R] /Count 2>>",
        (b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R"
         b" /Resources <</Font <</F1 7 0 R>>>>>>"),
        _content("Alpha lives on page one."),
        (b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 6 0 R"
         b" /Resources <</Font <</F1 7 0 R>>>>>>"),
        _content("Beta lives on page two."),
        b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>",
    ])


def no_text() -> bytes:
    """A scan-like PDF: one real page, no text operators at all."""
    return _pdf([
        b"<</Type /Catalog /Pages 2 0 R>>",
        b"<</Type /Pages /Kids [3 0 R] /Count 1>>",
        b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R>>",
        b"<</Length 0>>\nstream\n\nendstream",
    ])


if __name__ == "__main__":
    (HERE / "two_pages.pdf").write_bytes(two_pages())
    (HERE / "no_text.pdf").write_bytes(no_text())
    (HERE / "corrupt.pdf").write_bytes(b"%PDF-1.4\nthis is not a pdf body at all\n%%EOF\n")
    (HERE / "guide.md").write_text(
        "# Installation\n\nRun the installer.\n\n## Troubleshooting\n\n"
        "Restart the service.\n",
        encoding="utf-8",
    )
    (HERE / "notes.txt").write_text("Prima riga.\n\nSeconda riga con accenti: perché.\n",
                                    encoding="utf-8")
    print("fixtures written to", HERE)
