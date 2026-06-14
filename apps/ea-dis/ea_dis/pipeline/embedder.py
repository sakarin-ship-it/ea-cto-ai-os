"""Embedder: delegates to shared/lmstudio_client.py.

Rule A: all localhost:1234 calls must go through shared/lmstudio_client.py.
bge-m3 is the only resident model per M5 memory rules.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[4] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from lmstudio_client import EMBED_DIM, embed_batch, embed_text  # noqa: E402

__all__ = ["embed_text", "embed_batch", "EMBED_DIM"]
