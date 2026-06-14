"""Root conftest — add app root and shared/ onto sys.path before any test imports."""
from __future__ import annotations

import sys
from pathlib import Path

_APP_ROOT = Path(__file__).parent
_SHARED = _APP_ROOT.parents[1] / "shared"

for _p in (_APP_ROOT, _SHARED):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
