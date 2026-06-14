#!/usr/bin/env python3
"""EA CTO AI OS — 20-loop test harness.

Runs every app's pytest suite N times with bounded concurrency.
Enforces the CLAUDE.md Rule 5 "done" gate.

Usage (from repo root):
    python tests/harness/run_harness.py [--loops N] [--max-concurrency C] [--no-model-preload]

Exit 0 = all loops passed.
Exit 1 = one or more loops failed (failure output printed).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APPS_DIR = REPO_ROOT / "apps"
SHARED_DIR = REPO_ROOT / "shared"
PYTHON = sys.executable


# ── App discovery ─────────────────────────────────────────────────────────────


def discover_apps() -> list[tuple[str, Path]]:
    """Return (display_name, directory) for each app that has a pyproject.toml."""
    apps = []
    for app_dir in sorted(APPS_DIR.iterdir()):
        if app_dir.is_dir() and (app_dir / "pyproject.toml").exists():
            apps.append((app_dir.name, app_dir))
    return apps


# ── Model preload (best-effort, non-blocking) ─────────────────────────────────


def preload_model() -> bool:
    """Warm up LM Studio with qwen3-8b. Returns True on success.

    Skips gracefully when LM Studio is not running — all tests use mocked
    model calls, so this only matters for integration runs with a live stack.
    """
    try:
        sys.path.insert(0, str(SHARED_DIR))
        from lmstudio_client import chat_complete  # type: ignore[import]

        chat_complete("ping", model="qwen3-8b", max_tokens=1, timeout=15.0)
        _print("model   qwen3-8b loaded via LM Studio")
        return True
    except Exception as exc:  # noqa: BLE001
        _print(f"model   preload skipped (LM Studio not available: {exc})")
        return False


# ── Individual test run ───────────────────────────────────────────────────────


@dataclass
class RunResult:
    app: str
    loop: int
    passed: bool
    stdout: str
    stderr: str
    duration: float

    @property
    def tail(self) -> str:
        """Last 30 lines of combined output — shown on failure."""
        lines = (self.stdout + self.stderr).splitlines()
        return "\n".join(lines[-30:])


def run_one(app_name: str, app_dir: Path, loop: int) -> RunResult:
    """Run pytest for one app in one loop. Always returns; never raises."""
    env = {
        **os.environ,
        "PYTHONPATH": f"{SHARED_DIR}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }
    t0 = time.monotonic()
    proc = subprocess.run(
        [PYTHON, "-m", "pytest", "--tb=short", "-q", "--no-header"],
        cwd=app_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    return RunResult(
        app=app_name,
        loop=loop,
        passed=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration=time.monotonic() - t0,
    )


# ── Output helpers ────────────────────────────────────────────────────────────

_WIDTH = 60


def _print(msg: str) -> None:
    print(msg, flush=True)


def _status_line(done: int, total: int, result: RunResult) -> str:
    flag = "PASS" if result.passed else "FAIL"
    return (
        f"[{done:3d}/{total}] loop={result.loop:02d} "
        f"{result.app:<10s} {flag}  {result.duration:.2f}s"
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="EA CTO AI OS 20-loop harness (CLAUDE.md Rule 5)",
    )
    parser.add_argument("--loops", type=int, default=20, help="Number of loop iterations (default 20)")
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=2,
        dest="concurrency",
        help="Max simultaneous pytest processes (default 2, M5 safe)",
    )
    parser.add_argument(
        "--no-model-preload",
        action="store_true",
        help="Skip LM Studio model warm-up",
    )
    args = parser.parse_args()

    apps = discover_apps()
    if not apps:
        _print("ERROR: no apps found under apps/")
        return 1

    total_runs = args.loops * len(apps)
    _print(f"{'─' * _WIDTH}")
    _print(f"EA CTO AI OS harness  loops={args.loops}  concurrency={args.concurrency}")
    _print(f"apps  : {', '.join(n for n, _ in apps)}")
    _print(f"runs  : {total_runs}  ({args.loops} loops × {len(apps)} apps)")
    _print(f"{'─' * _WIDTH}")

    if not args.no_model_preload:
        preload_model()
        _print("")

    failures: list[RunResult] = []
    done = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(run_one, name, path, loop): (name, loop)
            for loop in range(1, args.loops + 1)
            for name, path in apps
        }
        for future in as_completed(futures):
            result = future.result()
            done += 1
            _print(_status_line(done, total_runs, result))
            if not result.passed:
                failures.append(result)

    _print("")
    _print(f"{'─' * _WIDTH}")

    if failures:
        _print(f"FAILED  {len(failures)}/{total_runs} runs")
        _print("")
        for f in sorted(failures, key=lambda r: (r.loop, r.app)):
            _print(f"  ✗ loop={f.loop:02d} {f.app}")
            for line in f.tail.splitlines():
                _print(f"      {line}")
            _print("")
        return 1

    _print(f"pytest: PASS · harness: PASS ({args.loops}/{args.loops})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
