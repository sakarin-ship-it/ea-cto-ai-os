"""FX monitor — fetches daily average rates from Bank of Thailand (BOT) API.

Conversion formula (all-integer, no float):
  amount_thb_satang = round(amount_foreign_minor * rate_thb_per_major_unit)

Where *amount_foreign_minor* is the foreign currency's minor unit (e.g. USD
cents).  The derivation:
  foreign_minor / 100  = foreign_major_units
  × rate               = THB
  × 100                = satang
  → satang = foreign_minor * rate   (the /100 and *100 cancel)

Rounding uses ROUND_HALF_UP via Decimal to stay deterministic.
"""
from __future__ import annotations

import logging
import os
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import httpx

from fci.constants import BOT_API_BASE, BOT_API_KEY_ENV

if TYPE_CHECKING:
    from fci.models import FXPosition

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    key = os.getenv(BOT_API_KEY_ENV, "")
    return {"X-IBM-Client-Id": key} if key else {}


def fetch_bot_rate(
    currency: str,
    date_str: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Return the raw BOT API JSON for *currency* (e.g. "USD")."""
    params: dict[str, str] = {"currency_id": currency.upper()}
    if date_str:
        params["start_period"] = date_str
        params["end_period"] = date_str

    resp = httpx.get(
        f"{BOT_API_BASE}/daily-avg-exch-rate/",
        params=params,
        headers=_headers(),
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def extract_mid_rate(bot_response: dict) -> Decimal:
    """Parse THB mid-rate from BOT response.  Falls back to selling rate."""
    try:
        entries = bot_response["result"]["data"]
        if not entries:
            raise ValueError("Empty data array in BOT response")
        row = entries[0]
        raw = row.get("mid_rate") or row.get("selling")
        if raw is None:
            raise ValueError("No mid_rate or selling in BOT response row")
        return Decimal(str(raw))
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Cannot parse BOT rate response: {exc}") from exc


def convert_to_thb_satang(amount_foreign_minor: int, rate_thb_per_major: Decimal) -> int:
    """Convert foreign minor units → THB satang using Decimal (ROUND_HALF_UP)."""
    result = Decimal(amount_foreign_minor) * rate_thb_per_major
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fetch_and_store_rate(currency: str, session, date_str: str | None = None) -> "FXPosition":
    """Fetch BOT rate and persist as an FXPosition record."""
    from fci.models import FXPosition

    data = fetch_bot_rate(currency, date_str=date_str)
    rate = extract_mid_rate(data)

    pos = FXPosition(
        currency_pair=f"{currency.upper()}THB",
        rate=rate,
        source="BOT",
        rate_date=date_str or "",
        amount_foreign_minor=0,
        amount_thb_satang=0,
    )
    session.add(pos)
    session.flush()
    return pos
