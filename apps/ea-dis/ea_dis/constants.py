"""Document type constants and privacy classification."""
from __future__ import annotations

from enum import Enum

CONFIDENCE_THRESHOLD = 0.85


class DocType(str, Enum):
    DOC_01 = "DOC-01"   # General correspondence
    DOC_02 = "DOC-02"   # Board minutes / resolutions
    DOC_03 = "DOC-03"   # Project reports
    DOC_04 = "DOC-04"   # Technical specifications
    DOC_05 = "DOC-05"   # JV / IP agreements        (SENSITIVE — local only)
    DOC_06 = "DOC-06"   # Contracts                 (SENSITIVE — local only)
    DOC_07 = "DOC-07"   # Financial documents       (SENSITIVE — local only)
    DOC_08 = "DOC-08"   # HR documents
    DOC_09 = "DOC-09"   # PDPA / personal data      (SENSITIVE — local only)
    DOC_10 = "DOC-10"   # Other / unclassified


# These doc types must NEVER be sent to cloud APIs.
SENSITIVE_DOC_TYPES: frozenset[DocType] = frozenset({
    DocType.DOC_05,
    DocType.DOC_06,
    DocType.DOC_07,
    DocType.DOC_09,
})


class DocStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"   # confidence < threshold
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Role(str, Enum):
    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"
