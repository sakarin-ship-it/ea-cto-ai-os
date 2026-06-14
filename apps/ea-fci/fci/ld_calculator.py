"""Liquidated Damages calculator — cap-aware, all-integer satang arithmetic.

Formula:
  daily_ld  = contract_value_satang * daily_rate_bps // 10_000
  raw_ld    = daily_ld * delay_days
  cap       = contract_value_satang * cap_pct // 100
  accrued   = min(raw_ld, cap)

No float is used anywhere.  Integer floor-division is intentional and
consistent with how Thai contracts define LD to the satang level.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LDResult:
    accrued_satang: int    # final LD (possibly capped)
    cap_satang: int        # maximum allowable LD
    raw_ld_satang: int     # uncapped gross LD
    is_capped: bool        # True when raw_ld > cap
    daily_ld_satang: int   # per-day charge


def calculate_ld(
    contract_value_satang: int,
    daily_rate_bps: int,   # basis points per day  (e.g. 10 = 0.1 %/day)
    delay_days: int,
    cap_pct: int,          # integer percent cap   (e.g. 10 = 10 %)
) -> LDResult:
    """Calculate LD with cap.  All values are integer satang; no float."""
    if contract_value_satang < 0:
        raise ValueError("contract_value_satang must be non-negative")
    if daily_rate_bps < 0:
        raise ValueError("daily_rate_bps must be non-negative")
    if delay_days < 0:
        raise ValueError("delay_days must be non-negative")
    if not (0 <= cap_pct <= 100):
        raise ValueError("cap_pct must be 0–100")

    daily_ld_satang: int = contract_value_satang * daily_rate_bps // 10_000
    raw_ld_satang: int = daily_ld_satang * delay_days
    cap_satang: int = contract_value_satang * cap_pct // 100

    is_capped = raw_ld_satang > cap_satang
    accrued_satang = cap_satang if is_capped else raw_ld_satang

    return LDResult(
        accrued_satang=accrued_satang,
        cap_satang=cap_satang,
        raw_ld_satang=raw_ld_satang,
        is_capped=is_capped,
        daily_ld_satang=daily_ld_satang,
    )
