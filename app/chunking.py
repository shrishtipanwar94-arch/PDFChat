"""Overlapping chunker that keeps the page number on every chunk."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    page: int
    position: int  # order of the chunk within the document
    content: str


def _normalise(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split(text: str, size: int, overlap: int) -> list[str]:
    """Split text into windows of about `size` chars overlapping by `overlap`.

    Each window ends at the last whitespace before the limit when there is one,
    so words are not cut in half.
    """
    if len(text) <= size:
        return [text] if text else []

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + size // 2, end)
            cut = max(cut, text.rfind("\n", start + size // 2, end))
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        next_start = end - overlap
        # Start the overlap on a word boundary as well.
        space = text.find(" ", next_start, end)
        if space != -1:
            next_start = space + 1
        start = max(next_start, start + 1)
    return pieces


def chunk_pages(
    pages: list[tuple[int, str]], size: int = 800, overlap: int = 120
) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks: list[Chunk] = []
    for page_number, text in pages:
        for piece in _split(_normalise(text), size, overlap):
            chunks.append(Chunk(page=page_number, position=len(chunks), content=piece))
    return chunks
