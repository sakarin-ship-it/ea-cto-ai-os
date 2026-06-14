"""Text chunker: splits document text into overlapping chunks for embedding."""
from __future__ import annotations

CHUNK_CHARS = 1500
OVERLAP_CHARS = 150


def chunk_text(text: str, chunk_chars: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split text into overlapping chunks on paragraph boundaries."""
    if not text.strip():
        return []

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) > chunk_chars and current_parts:
            chunks.append("\n\n".join(current_parts))
            # carry overlap: keep last para if short enough
            overlap_parts = []
            carry = 0
            for p in reversed(current_parts):
                if carry + len(p) <= overlap:
                    overlap_parts.insert(0, p)
                    carry += len(p)
                else:
                    break
            current_parts = overlap_parts
            current_len = carry

        current_parts.append(para)
        current_len += len(para)

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks or [text[:chunk_chars]]
