"""EA-LIE: every mandatory clause tag present in generated contract text."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT / "apps/ea-lie") not in sys.path:
    sys.path.insert(0, str(_ROOT / "apps/ea-lie"))

from lie.clauses import ALL_MANDATORY_CLAUSES, MANDATORY_CLAUSE_TAGS

from tests.harness.generators import contract_text_with_all_clauses

SCENARIO_ID = "lie_clauses"


def setup(seed: int) -> dict:
    text = contract_text_with_all_clauses(seed)
    return {
        "seed": seed,
        "contract_text": text,
        "expected_tags": sorted(MANDATORY_CLAUSE_TAGS),
    }


def run(data: dict) -> dict:
    text = data["contract_text"]
    found_tags = [tag for tag in MANDATORY_CLAUSE_TAGS if tag in text]
    missing_tags = [tag for tag in MANDATORY_CLAUSE_TAGS if tag not in text]
    return {
        "found_tags": sorted(found_tags),
        "missing_tags": sorted(missing_tags),
        "found_count": len(found_tags),
        "total_mandatory": len(MANDATORY_CLAUSE_TAGS),
        "all_found": len(missing_tags) == 0,
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    assert result["all_found"], (
        f"seed={seed}: missing mandatory clauses: {result['missing_tags']}"
    )
    assert result["found_count"] == result["total_mandatory"], (
        f"seed={seed}: found {result['found_count']}/{result['total_mandatory']} mandatory clauses"
    )

    # Each tag must be unique (##MC:XX## format)
    for tag in data["expected_tags"]:
        assert tag.startswith("##MC:") and tag.endswith("##"), (
            f"seed={seed}: tag {tag!r} does not match ##MC:XX## format"
        )

    # All clauses have distinct IDs
    ids = [c.id for c in ALL_MANDATORY_CLAUSES]
    assert len(ids) == len(set(ids)), f"seed={seed}: duplicate clause IDs found: {ids}"
