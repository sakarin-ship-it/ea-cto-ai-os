"""Shared pytest fixtures for EA-DIS tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def sample_text_general():
    return (
        "To: All Staff\nFrom: CTO Office\n\n"
        "Please be advised that the annual company meeting will be held on 15 July 2026. "
        "Attendance is mandatory for all department heads. Please confirm attendance by email."
    )


@pytest.fixture
def sample_text_contract():
    return (
        "SERVICE AGREEMENT\n\nThis agreement is entered into between ABC Engineering Co. Ltd. "
        "and XYZ Contractor Ltd. for the provision of EPC services. The contract value is "
        "THB 150,000,000. Liquidated damages shall apply at THB 500,000 per day of delay. "
        "Governing law: Thailand."
    )


@pytest.fixture
def sample_text_financial():
    return (
        "INVOICE #INV-2026-001\nDate: 2026-06-01\n\n"
        "Bill To: ABC Engineering Co. Ltd.\n"
        "Description: Structural Engineering Services - Phase 1\n"
        "Amount: THB 2,500,000\nVAT 7%: THB 175,000\nTotal: THB 2,675,000\n"
        "Payment due: 30 days from invoice date."
    )


@pytest.fixture
def sample_text_pdpa():
    return (
        "DATA PROCESSING CONSENT FORM\n\n"
        "Pursuant to the Personal Data Protection Act B.E. 2562 (PDPA), "
        "we collect your personal data including name, ID card number, and contact details "
        "for the purpose of employment. You have the right to withdraw consent at any time."
    )
