"""EA CTO AI OS — 20-iteration end-to-end scenario harness.

Each scenario runs 20 times with a fresh seed, exercising EA-DIS / EA-FCI /
EA-PIP / EA-LIE / n8n invariants against the real business-logic code.

Usage (from repo root):
    python -m tests.harness.runner
    python -m tests.harness.runner --scenario all --loops 20 --max-concurrency 2
    python -m tests.harness.runner --scenario fci_ld --loops 5 --max-concurrency 1
    python -m tests.harness.runner --preload-model

Exit 0 = PASS (every scenario 20/20).
Exit 1 = FAIL (first failure details printed; JSON report written).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Repo layout ───────────────────────────────────────────────────────────────

_REPO = Path(__file__).resolve().parents[2]
_SHARED = _REPO / "shared"
_APPS = {
    "ea-dis": _REPO / "apps/ea-dis",
    "ea-fci": _REPO / "apps/ea-fci",
    "ea-pip": _REPO / "apps/ea-pip",
    "ea-lie": _REPO / "apps/ea-lie",
}
_HARNESS = _REPO / "tests/harness"
_REPORTS = _REPO / "tests/reports"

# Prepend all app dirs + shared + tests root onto sys.path before any import
for _p in [str(_SHARED), str(_REPO), *[str(v) for v in _APPS.values()]]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Scenario registry ─────────────────────────────────────────────────────────

_SCENARIO_MODULES = [
    "tests.harness.scenarios.dis_classify",
    "tests.harness.scenarios.dis_rag",
    "tests.harness.scenarios.fci_three_way",
    "tests.harness.scenarios.fci_ld",
    "tests.harness.scenarios.fci_anomaly",
    "tests.harness.scenarios.pip_tier1",
    "tests.harness.scenarios.pip_tier2",
    "tests.harness.scenarios.lie_clauses",
    "tests.harness.scenarios.lie_review",
    "tests.harness.scenarios.lie_fidic",
    "tests.harness.scenarios.n8n_w03",
    "tests.harness.scenarios.n8n_w09",
    "tests.harness.scenarios.n8n_w12",
    "tests.harness.scenarios.integration",
]


def _load_scenarios(names: list[str]) -> list[Any]:
    mods = []
    for mod_path in _SCENARIO_MODULES:
        mod = importlib.import_module(mod_path)
        if "all" in names or mod.SCENARIO_ID in names:
            mods.append(mod)
    return mods


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class IterResult:
    scenario_id: str
    loop: int
    seed: int
    passed: bool
    duration_s: float
    error: str = ""
    setup_data: Any = field(default=None, repr=False)
    run_result: Any = field(default=None, repr=False)


@dataclass
class ScenarioReport:
    scenario_id: str
    loops: int
    passed: int
    failed: int
    total_duration_s: float
    failures: list[dict] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "PASS" if self.failed == 0 else "FAIL"


# ── Memory guard ──────────────────────────────────────────────────────────────

_MIN_FREE_RAM_BYTES = 2 * 1024 ** 3  # 2 GB


def _free_ram_bytes() -> int:
    try:
        import psutil
        return psutil.virtual_memory().available
    except ImportError:
        return _MIN_FREE_RAM_BYTES + 1  # assume OK if psutil missing


def _ram_ok() -> bool:
    return _free_ram_bytes() >= _MIN_FREE_RAM_BYTES


# ── Model pre-load ────────────────────────────────────────────────────────────

def _preload_model(model_name: str = "qwen3-8b") -> bool:
    """Warm one LM Studio model. Returns True on success.

    Skips gracefully if LM Studio is not running — all scenarios mock LM
    calls, so the harness still produces valid results without a live stack.
    """
    try:
        from lmstudio_client import chat_complete
        chat_complete("ping", model=model_name, max_tokens=1, timeout=15.0)
        _log(f"preload  {model_name} warmed via LM Studio (1 model loaded)")
        return True
    except Exception as exc:
        _log(f"preload  skipped — LM Studio not available: {exc}")
        return False


def _assert_single_model() -> None:
    """Assert only one model is loaded in LM Studio (via /api/v0/models state filter)."""
    try:
        import httpx
        resp = httpx.get("http://localhost:1234/api/v0/models", timeout=5.0)
        models = resp.json().get("data", [])
        loaded = [m for m in models if m.get("state") == "loaded"]
        if len(loaded) > 1:
            names = [m.get("id", "?") for m in loaded]
            raise RuntimeError(
                f"--preload-model violation: {len(loaded)} models loaded simultaneously: {names}. "
                "Only ONE model must be resident at a time (M5 16GB rule)."
            )
        _log(f"preload  model count OK ({len(loaded)} loaded)")
    except RuntimeError:
        raise
    except Exception as exc:
        _log(f"preload  model-count check skipped: {exc}")


# ── Single iteration ──────────────────────────────────────────────────────────

def _run_one(mod: Any, loop: int, seed: int) -> IterResult:
    t0 = time.monotonic()
    setup_data: Any = None
    run_result: Any = None
    try:
        setup_data = mod.setup(seed)
        run_result = mod.run(setup_data)
        mod.assert_invariants(setup_data, run_result)
        return IterResult(
            scenario_id=mod.SCENARIO_ID,
            loop=loop,
            seed=seed,
            passed=True,
            duration_s=time.monotonic() - t0,
            setup_data=setup_data,
            run_result=run_result,
        )
    except Exception:
        tb = traceback.format_exc()
        return IterResult(
            scenario_id=mod.SCENARIO_ID,
            loop=loop,
            seed=seed,
            passed=False,
            duration_s=time.monotonic() - t0,
            error=tb,
            setup_data=setup_data,
            run_result=run_result,
        )


# ── Scenario runner ───────────────────────────────────────────────────────────

def _run_scenario(
    mod: Any,
    loops: int,
    max_concurrency: int,
    seed_base: int,
    first_failure_cb,
) -> ScenarioReport:
    """Run one scenario for `loops` iterations.

    Checks RAM before each batch. Falls back to sequential if < 2 GB free.
    Calls first_failure_cb(result) on the first failure detected.
    """
    results: list[IterResult] = []
    seeds = [seed_base + i for i in range(loops)]

    batch_size = max_concurrency if max_concurrency > 1 else 1

    def _run_batch(batch_seeds: list[int], use_threads: bool) -> list[IterResult]:
        batch_results = []
        if use_threads and len(batch_seeds) > 1:
            with ThreadPoolExecutor(max_workers=len(batch_seeds)) as ex:
                futs = {ex.submit(_run_one, mod, i + 1, s): s
                        for i, s in enumerate(batch_seeds)}
                for fut in as_completed(futs):
                    batch_results.append(fut.result())
        else:
            for i, s in enumerate(batch_seeds):
                batch_results.append(_run_one(mod, i + 1, s))
        return batch_results

    for batch_start in range(0, loops, batch_size):
        batch = seeds[batch_start:batch_start + batch_size]

        # Assign correct loop numbers
        loop_numbers = list(range(batch_start + 1, batch_start + len(batch) + 1))

        # Memory guard
        use_threads = _ram_ok() and batch_size > 1
        if not use_threads and batch_size > 1:
            _log(f"  [{mod.SCENARIO_ID}] RAM < 2GB — falling back to sequential for this batch")

        if use_threads and len(batch) > 1:
            with ThreadPoolExecutor(max_workers=len(batch)) as ex:
                futs = {ex.submit(_run_one, mod, loop_numbers[j], s): (loop_numbers[j], s)
                        for j, s in enumerate(batch)}
                for fut in as_completed(futs):
                    r = fut.result()
                    results.append(r)
                    if not r.passed:
                        first_failure_cb(r)
        else:
            for j, s in enumerate(batch):
                r = _run_one(mod, loop_numbers[j], s)
                results.append(r)
                if not r.passed:
                    first_failure_cb(r)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    total_dur = sum(r.duration_s for r in results)

    failures = []
    for r in results:
        if not r.passed:
            failures.append({
                "loop": r.loop,
                "seed": r.seed,
                "error": r.error,
                "setup_data": _safe_json(r.setup_data),
                "run_result": _safe_json(r.run_result),
            })

    return ScenarioReport(
        scenario_id=mod.SCENARIO_ID,
        loops=loops,
        passed=passed,
        failed=failed,
        total_duration_s=total_dur,
        failures=failures,
    )


# ── Output ────────────────────────────────────────────────────────────────────

_WIDTH = 70


def _log(msg: str) -> None:
    print(msg, flush=True)


def _bar() -> None:
    _log("─" * _WIDTH)


def _safe_json(obj: Any) -> Any:
    """Recursively strip non-JSON-serialisable objects for the report."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        if isinstance(obj, dict):
            return {k: _safe_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_safe_json(v) for v in obj]
        return str(obj)


def _print_failure(r: IterResult) -> None:
    _log("")
    _log(f"FIRST FAILURE ── scenario={r.scenario_id}  loop={r.loop}  seed={r.seed}")
    _bar()
    if r.setup_data:
        _log("SEED + PAYLOAD:")
        try:
            _log(json.dumps(_safe_json(r.setup_data), indent=2, ensure_ascii=False)[:4000])
        except Exception:
            _log(str(r.setup_data)[:4000])
    if r.run_result:
        _log("RUN RESULT:")
        try:
            _log(json.dumps(_safe_json(r.run_result), indent=2, ensure_ascii=False)[:2000])
        except Exception:
            _log(str(r.run_result)[:2000])
    _log("TRACEBACK:")
    _log(r.error)
    _bar()


# ── Report ────────────────────────────────────────────────────────────────────

def _write_report(reports: list[ScenarioReport], loops: int, verdict: str) -> Path:
    _REPORTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _REPORTS / f"harness_{ts}.json"
    payload = {
        "timestamp": ts,
        "verdict": verdict,
        "loops": loops,
        "scenario_count": len(reports),
        "pass_count": sum(1 for r in reports if r.failed == 0),
        "fail_count": sum(1 for r in reports if r.failed > 0),
        "scenarios": [
            {
                "scenario_id": r.scenario_id,
                "verdict": r.verdict,
                "passed": r.passed,
                "failed": r.failed,
                "loops": r.loops,
                "total_duration_s": round(r.total_duration_s, 3),
                "failures": r.failures,
            }
            for r in reports
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="EA CTO AI OS 20-loop end-to-end harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        nargs="+",
        default=["all"],
        metavar="SCENARIO",
        help="Scenario ID(s) to run, or 'all' (default: all)",
    )
    parser.add_argument(
        "--loops",
        type=int,
        default=20,
        help="Iterations per scenario (default: 20)",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=2,
        dest="concurrency",
        help="Max parallel iterations per scenario batch (default: 2, M5-safe)",
    )
    parser.add_argument(
        "--preload-model",
        nargs="?",
        const="qwen3-8b",
        default=None,
        metavar="MODEL",
        dest="preload_model",
        help=(
            "Warm exactly one LM Studio model before the run and assert only one is loaded. "
            "Optionally supply the model ID (default: qwen3-8b). "
            "Bare flag uses the default. Omit entirely to skip preload."
        ),
    )
    parser.add_argument(
        "--seed-base",
        type=int,
        default=1000,
        dest="seed_base",
        help="Base seed (loop N gets seed_base + N - 1, default: 1000)",
    )
    args = parser.parse_args()

    # ── Header ────────────────────────────────────────────────────────────────
    _bar()
    _log("EA CTO AI OS — scenario harness")
    _log(f"  loops        : {args.loops}")
    _log(f"  concurrency  : {args.concurrency}")
    _log(f"  seed-base    : {args.seed_base}")
    _log(f"  scenarios    : {', '.join(args.scenario)}")
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / 1024**3
        free_gb = psutil.virtual_memory().available / 1024**3
        _log(f"  RAM          : {free_gb:.1f} GB free / {ram_gb:.1f} GB total")
    except ImportError:
        _log("  RAM          : psutil not available")
    _bar()

    # ── Model preload ──────────────────────────────────────────────────────────
    if args.preload_model:
        _preload_model(model_name=args.preload_model)
        _assert_single_model()
        _log("")

    # ── Load scenarios ─────────────────────────────────────────────────────────
    scenarios = _load_scenarios(args.scenario)
    if not scenarios:
        _log(f"ERROR: no scenarios matched {args.scenario!r}")
        _log(f"Available: {[m.split('.')[-1] for m in _SCENARIO_MODULES]}")
        return 1

    _log(f"Running {len(scenarios)} scenario(s) × {args.loops} loops "
         f"= {len(scenarios) * args.loops} total iterations")
    _log("")

    # ── Run ────────────────────────────────────────────────────────────────────
    reports: list[ScenarioReport] = []
    first_failure: Optional[IterResult] = None
    first_failure_printed = False

    def _on_failure(r: IterResult) -> None:
        nonlocal first_failure, first_failure_printed
        if first_failure is None:
            first_failure = r
        if not first_failure_printed:
            first_failure_printed = True
            _print_failure(r)

    t_start = time.monotonic()

    for mod in scenarios:
        t_mod = time.monotonic()
        _log(f"  ▶  {mod.SCENARIO_ID:<30s}  ({args.loops} loops × seed {args.seed_base}–{args.seed_base + args.loops - 1})")
        report = _run_scenario(
            mod=mod,
            loops=args.loops,
            max_concurrency=args.concurrency,
            seed_base=args.seed_base,
            first_failure_cb=_on_failure,
        )
        reports.append(report)
        elapsed = time.monotonic() - t_mod
        status = "PASS" if report.failed == 0 else f"FAIL ({report.failed}/{report.loops})"
        _log(f"     {report.scenario_id:<30s}  {status:<14s}  {elapsed:.2f}s")

    total_elapsed = time.monotonic() - t_start

    # ── Summary ────────────────────────────────────────────────────────────────
    _log("")
    _bar()
    all_pass = all(r.failed == 0 for r in reports)
    verdict = "PASS" if all_pass else "FAIL"
    total_loops = sum(r.loops for r in reports)
    total_passed = sum(r.passed for r in reports)
    _log(f"VERDICT  : {verdict}")
    _log(f"Scenarios: {sum(1 for r in reports if r.failed == 0)}/{len(reports)} passed")
    _log(f"Loops    : {total_passed}/{total_loops} passed")
    _log(f"Duration : {total_elapsed:.2f}s")

    report_path = _write_report(reports, args.loops, verdict)
    _log(f"Report   : {report_path}")
    _bar()

    if not all_pass:
        _log("")
        _log("FAILED SCENARIOS:")
        for r in reports:
            if r.failed > 0:
                _log(f"  ✗  {r.scenario_id}  ({r.failed}/{r.loops} iterations failed)")
        return 1

    _log(f"\nharness PASS — {len(scenarios)} scenario(s) × {args.loops} loops all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
