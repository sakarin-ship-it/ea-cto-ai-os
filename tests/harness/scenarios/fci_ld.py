"""EA-FCI: LD <= cap invariant, all-integer satang, is_capped strict >."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT / "apps/ea-fci") not in sys.path:
    sys.path.insert(0, str(_ROOT / "apps/ea-fci"))

from fci.ld_calculator import LDResult, calculate_ld

from tests.harness.generators import ld_scenario, ld_scenario_will_cap

SCENARIO_ID = "fci_ld"


def setup(seed: int) -> dict:
    if seed % 2 == 0:
        s = ld_scenario_will_cap(seed)
        expect_capped = True  # very likely; we verify in assert
    else:
        s = ld_scenario(seed)
        expect_capped = None  # unknown — we check the actual math

    return {
        "seed": seed,
        "contract_value_satang": s.contract_value_satang,
        "daily_rate_bps": s.daily_rate_bps,
        "delay_days": s.delay_days,
        "cap_pct": s.cap_pct,
        "expect_capped": expect_capped,
    }


def run(data: dict) -> dict:
    r = calculate_ld(
        contract_value_satang=data["contract_value_satang"],
        daily_rate_bps=data["daily_rate_bps"],
        delay_days=data["delay_days"],
        cap_pct=data["cap_pct"],
    )
    return {
        "accrued_satang": r.accrued_satang,
        "cap_satang": r.cap_satang,
        "raw_ld_satang": r.raw_ld_satang,
        "is_capped": r.is_capped,
        "daily_ld_satang": r.daily_ld_satang,
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # All values must be integers
    for key in ("accrued_satang", "cap_satang", "raw_ld_satang", "daily_ld_satang"):
        assert isinstance(result[key], int), f"seed={seed}: {key} must be int, got {type(result[key])}"

    # Core invariant: accrued <= cap always
    assert result["accrued_satang"] <= result["cap_satang"], (
        f"seed={seed}: accrued ({result['accrued_satang']}) > cap ({result['cap_satang']})"
    )

    # is_capped is True iff raw > cap (strict — equal is NOT capped)
    raw, cap = result["raw_ld_satang"], result["cap_satang"]
    expected_capped = raw > cap
    assert result["is_capped"] == expected_capped, (
        f"seed={seed}: is_capped={result['is_capped']} but raw={raw}, cap={cap} "
        f"(expected is_capped={expected_capped})"
    )

    # accrued = cap when capped, = raw when not
    if result["is_capped"]:
        assert result["accrued_satang"] == result["cap_satang"], (
            f"seed={seed}: when capped, accrued must equal cap"
        )
    else:
        assert result["accrued_satang"] == result["raw_ld_satang"], (
            f"seed={seed}: when not capped, accrued must equal raw_ld"
        )

    # daily_ld arithmetic
    cv = data["contract_value_satang"]
    bps = data["daily_rate_bps"]
    expected_daily = cv * bps // 10_000
    assert result["daily_ld_satang"] == expected_daily, (
        f"seed={seed}: daily_ld mismatch: got {result['daily_ld_satang']}, expected {expected_daily}"
    )
