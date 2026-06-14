"""Tests for compliance_checker — ALB threshold, completeness, bid bond.

Pure helpers (compute_alb_reference, is_alb) need no DB mocking.
run_compliance() is tested with MagicMock sessions.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from ea_pip.compliance_checker import (
    _check_bid_bond,
    _check_completeness,
    compute_alb_reference,
    is_alb,
)
from ea_pip.constants import ALB_THRESHOLD, REQUIRED_DOCUMENTS

# ─────────────────────────────────────────────────────────────────────────────
# Pure ALB helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeALBReference:
    def test_no_other_bids_returns_estimate(self):
        median, reference = compute_alb_reference([], 10_000_000)
        assert median is None
        assert reference == 10_000_000

    def test_median_of_odd_list(self):
        # [8M, 9M, 10M] → sorted mid index 1 → 9M
        median, _ = compute_alb_reference([10_000_000, 8_000_000, 9_000_000], 999)
        assert median == 9_000_000

    def test_median_of_even_list(self):
        # [8M, 10M] → (8M + 10M) // 2 = 9M
        median, _ = compute_alb_reference([10_000_000, 8_000_000], 999)
        assert median == 9_000_000

    def test_reference_is_min_of_median_and_estimate_when_median_lower(self):
        # median = 7M, estimate = 10M → reference = 7M
        _, reference = compute_alb_reference([7_000_000, 7_000_000], 10_000_000)
        assert reference == 7_000_000

    def test_reference_is_min_of_median_and_estimate_when_estimate_lower(self):
        # median = 12M, estimate = 8M → reference = 8M
        _, reference = compute_alb_reference([11_000_000, 12_000_000, 13_000_000], 8_000_000)
        assert reference == 8_000_000


class TestIsALB:
    """ALB flag: bid < ALB_THRESHOLD * reference (strict less-than)."""

    def test_bid_above_threshold_not_flagged(self):
        # 9M vs threshold 0.85 * 10M = 8.5M → not flagged
        assert not is_alb(9_000_000, 10_000_000)

    def test_bid_below_threshold_flagged(self):
        # 8.4M < 8.5M → flagged
        assert is_alb(8_400_000, 10_000_000)

    def test_bid_exactly_at_threshold_not_flagged(self):
        # 8.5M is NOT < 8.5M (strict) → not flagged
        assert not is_alb(8_500_000, 10_000_000)

    def test_alb_threshold_constant_value(self):
        assert ALB_THRESHOLD == 0.85

    def test_bid_at_zero_flagged(self):
        assert is_alb(0, 10_000_000)

    def test_large_bid_not_flagged(self):
        assert not is_alb(100_000_000, 10_000_000)


# ─────────────────────────────────────────────────────────────────────────────
# ALB integration: uses min(median, estimate)
# ─────────────────────────────────────────────────────────────────────────────


class TestALBIntegration:
    def _flag(self, bid, other_amounts, estimate):
        _, reference = compute_alb_reference(other_amounts, estimate)
        return is_alb(bid, reference)

    def test_median_lt_estimate_uses_median_as_reference(self):
        # median = 9M, estimate = 10M → reference = 9M, threshold = 7.65M
        # bid = 7_640_000 → flagged
        assert self._flag(7_640_000, [8_000_000, 9_000_000, 10_000_000], 10_000_000)

    def test_median_lt_estimate_not_flagged_at_threshold(self):
        # reference = 9M, threshold = 7.65M; bid = 7_650_000 → NOT flagged (strict <)
        assert not self._flag(7_650_000, [8_000_000, 9_000_000, 10_000_000], 10_000_000)

    def test_estimate_lt_median_uses_estimate(self):
        # median = 11M, estimate = 7M → reference = 7M, threshold = 5.95M
        # bid = 5_900_000 → flagged
        assert self._flag(5_900_000, [10_000_000, 11_000_000, 12_000_000], 7_000_000)


# ─────────────────────────────────────────────────────────────────────────────
# Completeness check
# ─────────────────────────────────────────────────────────────────────────────


class TestCompletenessCheck:
    def _make_session(self, document_types: list[str]):
        docs = [MagicMock(document_type=dt) for dt in document_types]
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = docs
        return session

    def test_all_required_present_passes(self):
        session = self._make_session(REQUIRED_DOCUMENTS)
        ok, note = _check_completeness(bid_id=1, session=session)
        assert ok
        assert note == ""

    def test_missing_one_document_fails(self):
        session = self._make_session(REQUIRED_DOCUMENTS[:-1])  # drop last
        ok, note = _check_completeness(bid_id=1, session=session)
        assert not ok
        assert "Missing" in note

    def test_empty_documents_fails(self):
        session = self._make_session([])
        ok, note = _check_completeness(bid_id=1, session=session)
        assert not ok
        assert len(note) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Bid bond check
# ─────────────────────────────────────────────────────────────────────────────


class TestBidBondCheck:
    def _make_bid(self, bond_satang):
        bid = MagicMock()
        bid.bid_bond_amount_satang = bond_satang
        return bid

    def _make_package(self, estimate):
        pkg = MagicMock()
        pkg.engineer_estimate_satang = estimate
        return pkg

    def test_bond_sufficient_passes(self):
        # 5% of 10M = 500K; bond = 500K → passes
        ok, _ = _check_bid_bond(self._make_bid(500_000), self._make_package(10_000_000))
        assert ok

    def test_bond_exactly_at_minimum_passes(self):
        # exactly 5% → passes
        ok, _ = _check_bid_bond(self._make_bid(500_000), self._make_package(10_000_000))
        assert ok

    def test_bond_below_minimum_fails(self):
        # bond = 499_999 < 500_000 → fails
        ok, note = _check_bid_bond(self._make_bid(499_999), self._make_package(10_000_000))
        assert not ok
        assert "required" in note.lower()
