"""EA-PIP: tier-2 blind scoring + ALB flagging invariants."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-pip"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ea_pip.compliance_checker import compute_alb_reference, is_alb
from ea_pip.constants import ALB_THRESHOLD

from tests.harness.generators import _rng

SCENARIO_ID = "pip_tier2"


def _make_scenario(seed: int) -> dict:
    """Build a bid scenario where the actual computed reference is known upfront.

    Strategy: make normal bids well above the estimate so that
    reference = min(median_normals, estimate) = estimate.
    Then alb_bid < 85% * estimate is unambiguous.
    """
    rng = _rng(seed)
    estimate = rng.randint(5_000_000_00, 50_000_000_00)

    # Normal bids: above estimate so median > estimate → reference = estimate
    normal_amounts = [
        int(estimate * rng.uniform(1.05, 1.25)),
        int(estimate * rng.uniform(1.05, 1.25)),
    ]
    # ALB bid: strictly below 80% of estimate (safely below 85% threshold)
    alb_factor = rng.uniform(0.50, 0.79)
    alb_amount = int(estimate * alb_factor)

    # Reference for ALB bid = min(median([normal1, normal2]), estimate)
    # median([normal1, normal2]) > estimate → reference = estimate
    _, ref_for_alb = compute_alb_reference(normal_amounts, estimate)

    # Normal bid reference = min(median([alb, other_normal]), estimate)
    # alb < estimate and other_normal > estimate → median < estimate
    # We pick a specific normal bid and check its reference
    normal_bid_amount = normal_amounts[0]
    other_amounts_for_normal = [alb_amount, normal_amounts[1]]
    _, ref_for_normal = compute_alb_reference(other_amounts_for_normal, estimate)

    return {
        "seed": seed,
        "estimate": estimate,
        "alb_bid_amount": alb_amount,
        "normal_bid_amount": normal_bid_amount,
        "other_amounts_for_alb": normal_amounts,
        "other_amounts_for_normal": other_amounts_for_normal,
        "ref_for_alb": ref_for_alb,
        "ref_for_normal": ref_for_normal,
    }


def setup(seed: int) -> dict:
    return _make_scenario(seed)


def run(data: dict) -> dict:
    estimate = data["estimate"]

    # Recompute reference + ALB for the flagged bid
    _, ref_alb = compute_alb_reference(data["other_amounts_for_alb"], estimate)
    alb_flagged = is_alb(data["alb_bid_amount"], ref_alb)

    # Recompute reference + ALB for the normal bid
    _, ref_norm = compute_alb_reference(data["other_amounts_for_normal"], estimate)
    normal_flagged = is_alb(data["normal_bid_amount"], ref_norm)

    # Boundary: exactly at 85% of ref_alb — must NOT be flagged (strict <)
    threshold_exact = int(Decimal(str(ref_alb)) * Decimal(str(ALB_THRESHOLD)))
    boundary_flagged = is_alb(threshold_exact, ref_alb)

    return {
        "alb_flagged": alb_flagged,
        "normal_flagged": normal_flagged,
        "boundary_flagged": boundary_flagged,
        "alb_bid_amount": data["alb_bid_amount"],
        "normal_bid_amount": data["normal_bid_amount"],
        "ref_alb": ref_alb,
        "ref_norm": ref_norm,
        "threshold_exact": threshold_exact,
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]
    ref = result["ref_alb"]
    threshold = result["threshold_exact"]

    # Planted ALB bid MUST be flagged (constructed < 80% of estimate → < 85% of ref)
    assert result["alb_flagged"] is True, (
        f"seed={seed}: ALB bid {result['alb_bid_amount']} should be < 85% of ref={ref} "
        f"(threshold={threshold}). Not flagged — check generator logic."
    )

    # Boundary at exactly floor(85% of ref) → NOT flagged (strict <, not <=)
    assert result["boundary_flagged"] is False, (
        f"seed={seed}: bid exactly at threshold={threshold} must NOT be "
        f"ALB-flagged (ALB is strict <, not <=)"
    )

    # ALB threshold value must be integer satang
    assert isinstance(result["threshold_exact"], int), (
        f"seed={seed}: ALB threshold must be integer satang"
    )
