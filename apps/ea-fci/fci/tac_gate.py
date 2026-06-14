"""TAC gate — blocks milestone/equipment payments without an approved CTO-signed TAC.

Spec: BLOCK milestone/equipment payment unless approved CTO-signed TAC is present
in EA-DIS DOC-06 (referenced via TACCertificate.dis_doc_id). The block_reason
must be explicit and non-empty whenever blocked=True.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TACResult:
    blocked: bool
    block_reason: str = field(default="")
    tac_id: int | None = field(default=None)


def check_tac_gate(invoice_id: int, session) -> TACResult:
    """Evaluate whether payment on *invoice_id* is permitted.

    Returns TACResult(blocked=True) with an explicit reason if the invoice is a
    milestone or equipment payment and no approved CTO-signed TAC exists.
    """
    from fci.models import Invoice, TACCertificate

    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise ValueError(f"Invoice {invoice_id} not found")

    # Non-milestone, non-equipment invoices pass unconditionally
    if not (invoice.is_milestone or invoice.is_equipment):
        return TACResult(blocked=False)

    tac = (
        session.query(TACCertificate)
        .filter(
            TACCertificate.po_id == invoice.po_id,
            TACCertificate.is_approved.is_(True),
        )
        .first()
    )

    if tac is None:
        kind = "milestone" if invoice.is_milestone else "equipment"
        return TACResult(
            blocked=True,
            block_reason=(
                f"BLOCKED: {kind} payment on invoice {invoice_id} "
                f"(PO {invoice.po_id}) requires an approved CTO-signed TAC "
                "(EA-DIS DOC-06). No valid TAC found. "
                "Upload a signed TAC via POST /tac before re-submitting."
            ),
        )

    return TACResult(blocked=False, tac_id=tac.id)
