"""Synthetic data generators for the EA CTO AI OS harness.

All generators accept a seed so each 20-iteration loop is reproducible
and isolated. No external I/O is performed here.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from faker import Faker

# Locales used across the suite
_LOCALES = ["en_US", "th_TH", "zh_CN"]


def _faker(seed: int, locale: str = "en_US") -> Faker:
    f = Faker(locale)
    Faker.seed(seed)
    f.seed_instance(seed)
    return f


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


# ── Monetary ──────────────────────────────────────────────────────────────────


def satang_amount(seed: int, min_thb: int = 100, max_thb: int = 10_000_000) -> int:
    """Random integer satang amount (THB × 100)."""
    rng = _rng(seed)
    return rng.randint(min_thb * 100, max_thb * 100)


def satang_unit_price(seed: int) -> int:
    rng = _rng(seed)
    return rng.randint(1_000_00, 500_000_00)  # 1k–5M THB per unit in satang


def satang_qty(seed: int) -> Decimal:
    rng = _rng(seed)
    # integer quantities to keep match arithmetic clean
    return Decimal(str(rng.randint(1, 1000)))


# ── Document text ─────────────────────────────────────────────────────────────

_THAI_DOC_SAMPLES = [
    "บันทึกการประชุม: ที่ประชุมมีมติเห็นชอบโครงการก่อสร้าง มูลค่า 150,000,000 บาท",
    "สัญญาจ้างเหมาก่อสร้าง ฉบับนี้ทำขึ้นระหว่าง บริษัท ก และ บริษัท ข",
    "ข้อมูลส่วนบุคคล: ชื่อ-นามสกุล เลขบัตรประชาชน ที่อยู่ตามทะเบียนบ้าน",
    "รายงานความก้าวหน้าโครงการ ไตรมาสที่ 2 ปี 2567",
    "ใบแจ้งหนี้เลขที่ INV-2567-001 จำนวนเงิน 2,500,000 บาท",
]

_ZH_DOC_SAMPLES = [
    "本采购合同由甲方与乙方签订，合同金额为人民币五百万元",
    "财务报告：本季度收入为人民币一千二百万元，同比增长15%",
    "技术规格说明：该系统需符合ISO 9001:2015质量管理体系要求",
]

_EN_DOC_SAMPLES = [
    "This EPC Agreement is entered into between Client Corp and Contractor Ltd.",
    "Invoice #INV-2026-001 for structural engineering services, total THB 2,500,000.",
    "Board Resolution: The board approves the capital expenditure of THB 50,000,000.",
    "PDPA Consent Form: We collect your personal data for employment purposes.",
    "Technical Specification: The system shall comply with IEC 61850 standards.",
    "JV Agreement between Thai Partner Co. and Foreign Investor Ltd. for IP licensing.",
]


def random_doc_text(seed: int) -> str:
    rng = _rng(seed)
    choice = rng.randint(0, 2)
    if choice == 0:
        return rng.choice(_THAI_DOC_SAMPLES)
    if choice == 1:
        return rng.choice(_ZH_DOC_SAMPLES)
    return rng.choice(_EN_DOC_SAMPLES)


def doc_text_for_type(seed: int, doc_type: str) -> str:
    """Return text that should classify to a specific doc type."""
    type_texts = {
        "DOC-01": "To: All staff\nFrom: CTO Office\nSubject: Company meeting",
        "DOC-02": "BOARD RESOLUTION: The board resolves to approve the budget.",
        "DOC-03": "PROJECT REPORT Q2 2026: Progress on Phase 2 is 65% complete.",
        "DOC-04": "TECHNICAL SPECIFICATION: Compressive strength ≥ 30 MPa.",
        "DOC-05": "JV AGREEMENT: Joint venture between Thai Partner and Foreign Investor for IP.",
        "DOC-06": "EPC CONTRACT: This construction contract value is THB 150,000,000.",
        "DOC-07": "INVOICE #001: Total amount THB 2,500,000 payable within 30 days.",
        "DOC-08": "EMPLOYMENT CONTRACT: Basic salary THB 85,000/month.",
        "DOC-09": "PDPA CONSENT: Personal data including ID card number and address.",
        "DOC-10": "Miscellaneous documents not classified elsewhere.",
    }
    return type_texts.get(doc_type, _EN_DOC_SAMPLES[0])


# ── Bid sets ──────────────────────────────────────────────────────────────────


@dataclass
class BidData:
    bid_id: int
    supplier_id: int
    amount_satang: int
    bond_amount_satang: int
    is_compliant: bool = True
    is_alb_flagged: bool = False


def bid_set_tier1(seed: int, count: int = 4) -> tuple[int, list[BidData]]:
    """Return (engineer_estimate_satang, bids) with >=3 compliant non-ALB bids.

    The lowest-price bid is always bid_id=1 with a clearly lowest amount.
    """
    rng = _rng(seed)
    estimate = rng.randint(5_000_000_00, 50_000_000_00)  # 5M–500M THB

    # bid bond must be >= 5% of estimate
    min_bond = estimate * 5 // 100

    bids = []
    # First bid is the lowest (winner)
    base_price = int(estimate * rng.uniform(0.88, 0.95))
    bids.append(BidData(
        bid_id=1,
        supplier_id=101,
        amount_satang=base_price,
        bond_amount_satang=min_bond + rng.randint(0, min_bond // 10),
        is_compliant=True,
        is_alb_flagged=False,
    ))
    # Remaining bids are higher
    for i in range(2, count + 1):
        amt = int(base_price * rng.uniform(1.01, 1.20))
        bids.append(BidData(
            bid_id=i,
            supplier_id=100 + i,
            amount_satang=amt,
            bond_amount_satang=min_bond + rng.randint(0, min_bond // 10),
            is_compliant=True,
            is_alb_flagged=False,
        ))
    return estimate, bids


def bid_set_tier2_alb(seed: int) -> tuple[int, list[BidData]]:
    """Return (engineer_estimate_satang, bids) where bid_id=2 is ALB-flagged.

    bid_id=2 has amount < 85% of reference (engineer estimate when it's min).
    """
    rng = _rng(seed)
    estimate = rng.randint(5_000_000_00, 50_000_000_00)
    min_bond = estimate * 5 // 100

    normal_amt = int(estimate * rng.uniform(0.88, 0.98))
    # ALB bid: strictly below 85% threshold
    alb_amt = int(estimate * rng.uniform(0.60, 0.84))

    bids = [
        BidData(1, 101, normal_amt, min_bond + 1_000_00, True, False),
        BidData(2, 102, alb_amt, min_bond + 1_000_00, True, True),  # ALB
        BidData(3, 103, int(normal_amt * 1.05), min_bond + 1_000_00, True, False),
    ]
    return estimate, bids


# ── EPC milestones ────────────────────────────────────────────────────────────


@dataclass
class MilestoneData:
    milestone_id: str
    description: str
    planned_date: date
    actual_date: Optional[date]
    overdue_days: int  # positive = overdue
    contract_value_satang: int
    daily_rate_bps: int
    cap_pct: int


def epc_milestone(seed: int) -> MilestoneData:
    rng = _rng(seed)
    f = _faker(seed)
    today = date(2026, 6, 14)
    overdue = rng.randint(-30, 120)  # negative = ahead of schedule
    planned = today - timedelta(days=rng.randint(10, 200))
    actual = planned + timedelta(days=overdue) if overdue > 0 else None
    return MilestoneData(
        milestone_id=f"MS-{rng.randint(1, 999):03d}",
        description=f.sentence(nb_words=6),
        planned_date=planned,
        actual_date=actual,
        overdue_days=max(0, overdue),
        contract_value_satang=rng.randint(10_000_000_00, 500_000_000_00),
        daily_rate_bps=rng.randint(5, 20),
        cap_pct=rng.randint(5, 15),
    )


# ── Contracts ─────────────────────────────────────────────────────────────────

_ALL_TAGS = ["##MC:IR##", "##MC:LD##", "##MC:PDPA##", "##MC:SEC##", "##MC:ESIG##"]


def contract_text_with_all_clauses(seed: int) -> str:
    """Generate contract text that embeds ALL 5 mandatory clause tags."""
    f = _faker(seed)
    header = (
        f"EPC CONTRACT\n\nParties: {f.company()} and {f.company()}\n"
        f"Date: {f.date_this_year()}\nValue: THB {f.random_int(1, 500):,},000,000\n\n"
    )
    body = "\n\n".join([
        "ARTICLE 1 — SCOPE\n" + f.paragraph(nb_sentences=3),
        "ARTICLE 2 — PAYMENT\n" + f.paragraph(nb_sentences=2),
        "ARTICLE 3 — INJUNCTIVE RELIEF\n##MC:IR##\n" + f.paragraph(nb_sentences=2),
        "ARTICLE 4 — LIQUIDATED DAMAGES\n##MC:LD##\n" + f.paragraph(nb_sentences=2),
        "ARTICLE 5 — PERSONAL DATA\n##MC:PDPA##\n" + f.paragraph(nb_sentences=2),
        "ARTICLE 6 — SECURITIES DISCLOSURE\n##MC:SEC##\n" + f.paragraph(nb_sentences=2),
        "ARTICLE 7 — E-SIGNATURE\n##MC:ESIG##\n" + f.paragraph(nb_sentences=2),
    ])
    return header + body


def contract_text_missing_clauses(seed: int, missing: list[str]) -> str:
    """Generate contract text with some mandatory clause tags absent."""
    full = contract_text_with_all_clauses(seed)
    for tag in missing:
        full = full.replace(tag, "[OMITTED]")
    return full


# ── FIDIC events ──────────────────────────────────────────────────────────────


@dataclass
class FIDICEventData:
    edition_key: str
    clause: str
    trigger_date: date
    days_until_deadline: int  # from trigger date
    contract_id: str


_FIDIC_CLAUSES = {
    "RED_1999": ["20.1", "2.5", "8.4"],
    "YELLOW_1999": ["20.1", "2.5", "8.4"],
    "RED_2017": ["20.2.1", "20.2.4", "2.5"],
    "SILVER_1999": ["20.1", "2.5"],
}


def fidic_event_near_timebar(seed: int) -> FIDICEventData:
    """Generate a FIDIC event where the deadline is 0-35 days away."""
    rng = _rng(seed)
    today = date(2026, 6, 14)
    edition_key = rng.choice(list(_FIDIC_CLAUSES.keys()))
    clause = rng.choice(_FIDIC_CLAUSES[edition_key])
    # deadline_days for RED_1999/20.1 is 28; we want the deadline to be near
    days_until_deadline = rng.randint(0, 35)
    # trigger_date = today - (28 - days_until_deadline) so deadline = today + days_until_deadline
    deadline_days_map = {
        "20.1": 28, "2.5": 28, "8.4": 28, "20.2.1": 28, "20.2.4": 84, "13.3": 14,
    }
    dd = deadline_days_map.get(clause, 28)
    trigger_date = today - timedelta(days=dd - days_until_deadline)
    return FIDICEventData(
        edition_key=edition_key,
        clause=clause,
        trigger_date=trigger_date,
        days_until_deadline=days_until_deadline,
        contract_id=f"CTR-EPC-2026-{rng.randint(1, 999):03d}",
    )


# ── Invoice + PO + GRN ────────────────────────────────────────────────────────


@dataclass
class ThreeWayData:
    po_qty: Decimal
    po_unit_price_satang: int
    grn_qty: Decimal
    inv_qty: Decimal
    inv_unit_price_satang: int
    is_milestone: bool
    has_approved_tac: bool
    po_id: int = 1
    grn_id: int = 1
    invoice_id: int = 1


def three_way_exact_match(seed: int, is_milestone: bool = False) -> ThreeWayData:
    """All three quantities and prices agree exactly."""
    rng = _rng(seed)
    qty = Decimal(str(rng.randint(1, 500)))
    price = rng.randint(1_000_00, 10_000_000_00)
    has_tac = rng.choice([True, False]) if not is_milestone else rng.choice([True, False])
    return ThreeWayData(
        po_qty=qty,
        po_unit_price_satang=price,
        grn_qty=qty,
        inv_qty=qty,
        inv_unit_price_satang=price,
        is_milestone=is_milestone,
        has_approved_tac=has_tac,
    )


def three_way_milestone_no_tac(seed: int) -> ThreeWayData:
    """Milestone invoice with NO approved TAC — must be blocked."""
    data = three_way_exact_match(seed, is_milestone=True)
    data.has_approved_tac = False
    return data


# ── LD scenario ───────────────────────────────────────────────────────────────


@dataclass
class LDScenarioData:
    contract_value_satang: int
    daily_rate_bps: int
    delay_days: int
    cap_pct: int


def ld_scenario(seed: int) -> LDScenarioData:
    rng = _rng(seed)
    return LDScenarioData(
        contract_value_satang=rng.randint(1_000_000_00, 500_000_000_00),
        daily_rate_bps=rng.randint(1, 50),
        delay_days=rng.randint(0, 365),
        cap_pct=rng.randint(1, 20),
    )


def ld_scenario_will_cap(seed: int) -> LDScenarioData:
    """LD scenario where raw_ld > cap (capping is triggered)."""
    rng = _rng(seed)
    cv = rng.randint(10_000_000_00, 100_000_000_00)
    rate = rng.randint(20, 50)   # high rate
    delay = rng.randint(100, 365)  # long delay
    cap = rng.randint(1, 5)        # low cap
    return LDScenarioData(cv, rate, delay, cap)


# ── Anomaly detection ─────────────────────────────────────────────────────────


def anomaly_feature_matrix(seed: int, n_normal: int = 20) -> list[list[float]]:
    """Generate features with one planted outlier at index 0."""
    rng = _rng(seed)
    normal_range = (1_000_000, 10_000_000)
    # Planted outlier: 100x normal amount
    outlier = [float(rng.randint(500_000_000, 1_000_000_000)), float(rng.randint(1, 5)), float(rng.randint(500_000_000, 1_000_000_000))]
    normals = [
        [float(rng.randint(*normal_range)), float(rng.randint(1, 100)), float(rng.randint(10_000, 200_000))]
        for _ in range(n_normal)
    ]
    return [outlier] + normals


# ── Breach events ─────────────────────────────────────────────────────────────


@dataclass
class BreachEventData:
    contract_id: str
    event_type: str
    description: str
    source: str  # "EA-FCI" | "EA-DIS" | "EA-PIP"


def breach_event(seed: int) -> BreachEventData:
    rng = _rng(seed)
    f = _faker(seed)
    sources = ["EA-FCI", "EA-DIS", "EA-PIP"]
    event_types = ["PAYMENT_DEFAULT", "DELIVERY_DELAY", "QUALITY_BREACH", "COMPLIANCE_VIOLATION"]
    return BreachEventData(
        contract_id=f"CTR-EPC-2026-{rng.randint(1, 999):03d}",
        event_type=rng.choice(event_types),
        description=f.sentence(nb_words=15),
        source=rng.choice(sources),
    )
