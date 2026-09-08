from __future__ import annotations


def chunk_text(text: str, *, size: int = 1000, overlap: int = 200) -> list[str]:
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    text = text.strip()
    if not text:
        return []
    step = size - overlap
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(piece)
    return chunks
