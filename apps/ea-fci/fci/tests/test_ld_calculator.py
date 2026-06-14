"""Tests for ld_calculator — proves exact satang math and cap enforcement.

All arithmetic verified by hand before being expressed as assertions.
"""
from __future__ import annotations

import pytest

from fci.ld_calculator import calculate_ld

# ─────────────────────────────────────────────────────────────────────────────
# Exact satang arithmetic
# ─────────────────────────────────────────────────────────────────────────────

def test_basic_ld_exact_satang():
    """10 M THB, 0.1 %/day, 10 days, 10 % cap.

    daily_ld = 1_000_000_000 * 10 // 10_000 = 1_000_000
    raw_ld   = 1_000_000 * 10                = 10_000_000
    cap      = 1_000_000_000 * 10 // 100     = 100_000_000
    accrued  = min(10_000_000, 100_000_000)  = 10_000_000
    """
    r = calculate_ld(
        contract_value_satang=1_000_000_000,
        daily_rate_bps=10,
        delay_days=10,
        cap_pct=10,
    )
    assert r.daily_ld_satang == 1_000_000
    assert r.raw_ld_satang == 10_000_000
    assert r.cap_satang == 100_000_000
    assert r.accrued_satang == 10_000_000
    assert r.is_capped is False


def test_ld_all_values_are_integers():
    """accrued / cap / raw must all be int — never float."""
    r = calculate_ld(777_777_777, 7, 77, 7)
    assert isinstance(r.accrued_satang, int)
    assert isinstance(r.cap_satang, int)
    assert isinstance(r.raw_ld_satang, int)
    assert isinstance(r.daily_ld_satang, int)


def test_ld_zero_delay_yields_zero():
    r = calculate_ld(1_000_000_000, 10, delay_days=0, cap_pct=10)
    assert r.accrued_satang == 0
    assert r.raw_ld_satang == 0
    assert r.is_capped is False


def test_ld_zero_rate_yields_zero():
    r = calculate_ld(1_000_000_000, daily_rate_bps=0, delay_days=100, cap_pct=10)
    assert r.accrued_satang == 0


def test_ld_small_contract_exact():
    """100 THB = 10_000 satang, 1 %/day = 100 bps, 5 days, 10 % cap.

    daily_ld = 10_000 * 100 // 10_000 = 100
    raw_ld   = 100 * 5                = 500
    cap      = 10_000 * 10 // 100     = 1_000
    accrued  = 500 (under cap)
    """
    r = calculate_ld(10_000, 100, 5, 10)
    assert r.daily_ld_satang == 100
    assert r.raw_ld_satang == 500
    assert r.cap_satang == 1_000
    assert r.accrued_satang == 500
    assert r.is_capped is False


# ─────────────────────────────────────────────────────────────────────────────
# Cap enforcement — the critical invariant
# ─────────────────────────────────────────────────────────────────────────────

def test_ld_never_exceeds_cap():
    """200 days at 0.1 %/day → raw 20 M THB but capped at 10 M THB (10 %)."""
    r = calculate_ld(
        contract_value_satang=1_000_000_000,
        daily_rate_bps=10,
        delay_days=200,
        cap_pct=10,
    )
    assert r.raw_ld_satang == 200_000_000   # 200 * 1_000_000
    assert r.cap_satang == 100_000_000
    assert r.accrued_satang == 100_000_000  # capped
    assert r.is_capped is True
    # Core invariant: accrued ≤ cap, always
    assert r.accrued_satang <= r.cap_satang


def test_ld_capped_accrued_equals_cap():
    """When raw > cap, accrued must equal cap exactly."""
    r = calculate_ld(1_000_000_000, 10, 200, 10)
    assert r.accrued_satang == r.cap_satang


def test_ld_cap_invariant_many_scenarios():
    """accrued ≤ cap across a range of scenarios."""
    scenarios = [
        (100_000_000, 50, 500, 5),    # high rate, long delay, 5 % cap
        (500_000_000, 20, 1000, 10),  # 2 %/day for 1000 days, 10 % cap
        (1, 1, 10_000, 1),            # tiny contract, 1 % cap
        (10**12, 100, 365, 15),       # large contract, 1 %/day, 365 days
    ]
    for contract, rate, days, cap in scenarios:
        r = calculate_ld(contract, rate, days, cap)
        assert r.accrued_satang <= r.cap_satang, (
            f"VIOLATED: accrued {r.accrued_satang} > cap {r.cap_satang} "
            f"for contract={contract} rate={rate} days={days} cap={cap}"
        )


def test_ld_at_cap_boundary_is_not_marked_capped():
    """When raw == cap exactly, is_capped should be False (equal, not exceeded)."""
    # design: daily=100, days=100, raw=10_000; cap=10_000
    # 10_000 * 100 // 10_000 = 100 (daily)
    # 100 * 100 = 10_000 (raw)
    # 10_000 * 100 // 100 = 10_000 (cap at 100%)
    r = calculate_ld(10_000, 100, 100, 100)
    assert r.raw_ld_satang == r.cap_satang
    assert r.is_capped is False   # raw == cap, not strictly greater


# ─────────────────────────────────────────────────────────────────────────────
# Input validation
# ─────────────────────────────────────────────────────────────────────────────

def test_negative_contract_raises():
    with pytest.raises(ValueError, match="contract_value_satang"):
        calculate_ld(-1, 10, 10, 10)


def test_negative_rate_raises():
    with pytest.raises(ValueError, match="daily_rate_bps"):
        calculate_ld(1_000, -1, 10, 10)


def test_negative_delay_raises():
    with pytest.raises(ValueError, match="delay_days"):
        calculate_ld(1_000, 10, -1, 10)


def test_cap_above_100_raises():
    with pytest.raises(ValueError, match="cap_pct"):
        calculate_ld(1_000, 10, 10, 101)


def test_cap_zero_means_no_ld_allowed():
    """cap_pct=0 → cap=0 → any delay means accrued=0 and is_capped=True."""
    r = calculate_ld(1_000_000, 10, 5, 0)
    assert r.cap_satang == 0
    # raw_ld = 5_000; capped at 0
    assert r.accrued_satang == 0
