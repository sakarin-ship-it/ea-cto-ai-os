"""Root conftest for EA-DIS — adds app to sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

# Make the `ea_dis` package importable without install
sys.path.insert(0, str(Path(__file__).parent))
