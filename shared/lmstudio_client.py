"""Shared LM Studio client — ONE model at a time per M5 16GB memory rules.

All sensitive doc processing (DOC-05/06/07/09) routes through here.
Cloud APIs never receive sensitive text.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

LMSTUDIO_BASE = "http://localhost:1234/v1"
PRIMARY_MODEL = "qwen3-8b"
FAST_MODEL = "llama-3.2-3b"
EMBED_MODEL = "bge-m3"
EMBED_DIM = 1024

_CHUNK_CHARS = 6_000  # safe for 4096-token ctx with Thai bilingual text


def chat_complete(
    prompt: str,
    system: str = "",
    model: str = PRIMARY_MODEL,
    max_tokens: int = 2048,
    timeout: float = 120.0,
) -> str:
    """Single call to LM Studio OpenAI-compatible endpoint."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = httpx.post(
        f"{LMSTUDIO_BASE}/chat/completions",
        json={"model": model, "messages": messages, "max_tokens": max_tokens, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chunk_and_complete(
    text: str,
    instruction: str,
    model: str = PRIMARY_MODEL,
    chunk_chars: int = _CHUNK_CHARS,
) -> list[str]:
    """Process long text sequentially in chunks (M5 note: never exceed 4096 ctx).

    For very large contracts each chunk is summarised; results returned in order.
    """
    chunks = _split_paragraphs(text, chunk_chars)
    results: list[str] = []
    for i, chunk in enumerate(chunks):
        prompt = f"{instruction}\n\n[CHUNK {i + 1}/{len(chunks)}]\n{chunk}"
        try:
            results.append(chat_complete(prompt, model=model))
        except Exception as exc:
            logger.error("lmstudio chunk %d failed: %s", i, exc)
            results.append("")
    return results


def embed_text(text: str, timeout: float = 60.0) -> list[float]:
    """Return bge-m3 embedding for a single text (bge-m3 stays resident per M5 rules)."""
    resp = httpx.post(
        f"{LMSTUDIO_BASE}/embeddings",
        json={"model": EMBED_MODEL, "input": text},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts sequentially (M5: one at a time)."""
    results: list[list[float]] = []
    for text in texts:
        try:
            results.append(embed_text(text))
        except Exception as exc:
            logger.error("lmstudio embed failed: %s", exc)
            results.append([0.0] * EMBED_DIM)
    return results


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    paras = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for para in paras:
        if size + len(para) > max_chars and current:
            chunks.append("\n\n".join(current))
            current, size = [para], len(para)
        else:
            current.append(para)
            size += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [""]
