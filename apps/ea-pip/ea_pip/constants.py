"""EA-PIP constants and enumerations."""
from __future__ import annotations

from enum import Enum

# ── LM Studio / qwen3-8b (on-prem, sequential only) ─────────────────────────
LM_STUDIO_BASE = "http://localhost:1234/v1"
TECHNICAL_MODEL = "qwen3-8b"

# ── DBD API (Thailand Department of Business Development) ────────────────────
DBD_API_BASE = "https://opendata.dbd.go.th/api"
DBD_API_KEY_ENV = "DBD_API_KEY"

# ── Scoring: 5 evaluation criteria ───────────────────────────────────────────
CRITERIA = ["technical", "experience", "personnel", "financial", "price"]

TIER2_WEIGHTS: dict[str, int] = {
    "technical": 35,
    "experience": 20,
    "personnel": 15,
    "financial": 10,
    "price": 20,
}  # sum = 100

TIER3_WEIGHTS: dict[str, int] = {
    "technical": 20,
    "experience": 15,
    "personnel": 10,
    "financial": 5,
    "price": 50,
}  # sum = 100

# ── Compliance thresholds ─────────────────────────────────────────────────────
ALB_THRESHOLD = 0.85          # Abnormally Low Bid: < 85 % of min(median, estimate)
BID_BOND_PCT = 0.05           # bid bond must be >= 5 % of engineer estimate
OUTLIER_ZSCORE_THRESHOLD = 1.5

# ── Tier-1 autoselect ────────────────────────────────────────────────────────
MIN_COMPLIANT_BIDS_TIER1 = 3  # minimum compliant non-ALB bids to auto-select

# ── Award ────────────────────────────────────────────────────────────────────
AWARD_VALIDITY_DAYS = 45

# ── API authentication ────────────────────────────────────────────────────────
PIP_API_KEY_ENV = "PIP_API_KEY"    # read from env; 401 if absent or wrong

# ── Input size limits ─────────────────────────────────────────────────────────
MAX_SCOPE_LENGTH = 2000            # chars; scope_en sent to Claude API must stay non-sensitive
MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB per bid document
MAX_TECHNICAL_TEXT = 8000          # chars; stored in DB before qwen3 truncation at 4000

# ── Supplier validation ───────────────────────────────────────────────────────
THAI_TIN_PATTERN = r"^\d{13}$"    # Thai 13-digit TIN

# ── Required bid document categories for completeness check ──────────────────
REQUIRED_DOCUMENTS = [
    "technical_proposal",
    "financial_proposal",
    "company_registration",
    "bid_bond_certificate",
]


class ProcurementTier(str, Enum):
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EVALUATING = "EVALUATING"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    ALB_FLAGGED = "ALB_FLAGGED"
    WITHDRAWN = "WITHDRAWN"


class DBDStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


class AwardStatus(str, Enum):
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FALLBACK_PENDING = "FALLBACK_PENDING"
    FALLBACK_ACCEPTED = "FALLBACK_ACCEPTED"
    FALLBACK_REJECTED = "FALLBACK_REJECTED"
