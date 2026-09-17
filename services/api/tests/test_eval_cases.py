"""Guards the eval case file against drift from the API contract.

The cases are exercised by hand today, so nothing else catches a case that
would 422 or hit a dealer group/category with no evidence fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.evidence.fixtures import FixtureEvidenceRetriever
from app.evidence.retrieval import EvidenceRequest
from app.mock_data import CATEGORY_IDS
from app.models import SupportPlanRequest

_CASES_PATH = Path(__file__).resolve().parents[3] / "evals" / "synthetic_cases.jsonl"


def _cases() -> list[dict[str, Any]]:
    lines = _CASES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_cases_file_is_not_empty() -> None:
    assert _cases()


@pytest.mark.parametrize("case", _cases(), ids=lambda c: str(c["id"]))
def test_case_satisfies_the_request_contract(case: dict[str, Any]) -> None:
    SupportPlanRequest(
        dealership_id=case["dealership_id"],
        category=case["category"],
        concern_text=case["concern_text"],
        dealer_group_id=case["dealer_group_id"],
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda c: str(c["id"]))
async def test_case_resolves_to_real_evidence(case: dict[str, Any]) -> None:
    assert case["category"] in CATEGORY_IDS
    bundle = await FixtureEvidenceRetriever().retrieve(
        EvidenceRequest(
            dealer_group_id=case["dealer_group_id"],
            category=case["category"],
            detected_need_hint="",
        )
    )
    assert bundle.citations
