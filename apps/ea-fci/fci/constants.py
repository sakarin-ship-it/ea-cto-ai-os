"""EA-FCI constants and enumerations."""
from __future__ import annotations

from enum import Enum

# Bank of Thailand FX API
BOT_API_BASE = "https://apigw1.bot.or.th/bot/public/Stat-ExchangeRate/v2"
BOT_API_KEY_ENV = "BOT_API_KEY"

# Three-way match tolerances
QTY_TOLERANCE = "0.02"     # ±2% as a Decimal-safe string
PRICE_TOLERANCE_BPS = 50   # ±0.5% expressed as basis points (50 bps = 0.5%)

# ETDA / WebAuthn relying-party defaults (override via env vars in api.py / esign.py)
DEFAULT_RP_ID = "ea-fci.internal"
DEFAULT_RP_NAME = "EA-FCI Financial Control"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    BLOCKED = "BLOCKED"


class POStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    BLOCKED = "BLOCKED"


class MatchStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    PARTIAL = "PARTIAL"


class EntityType(str, Enum):
    INVOICE = "invoice"
    PAYMENT = "payment"
    PO = "purchase_order"
    GRN = "grn"
    TAC = "tac_certificate"
    LD = "ld_accrual"
    FX = "fx_position"
