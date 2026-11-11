"""Every category the UI can offer must have evidence in every dealer group.

The recommendation contract requires at least one citation, so a category
with no fixtures can never produce a valid plan - it fails at protocol
validation instead. This test makes that gap loud.
"""

from __future__ import annotations

import pytest

from app.evidence.fixtures import FixtureEvidenceRetriever, list_available_dealer_groups
from app.evidence.retrieval import EvidenceRequest
from app.mock_data import CATEGORY_IDS


@pytest.mark.parametrize("dealer_group_id", list_available_dealer_groups())
@pytest.mark.parametrize("category", CATEGORY_IDS)
async def test_every_dealer_group_has_evidence_for_every_category(
    dealer_group_id: str, category: str
) -> None:
    bundle = await FixtureEvidenceRetriever().retrieve(
        EvidenceRequest(dealer_group_id=dealer_group_id, category=category, detected_need_hint="")
    )
    assert bundle.citations, f"no evidence fixtures for {dealer_group_id}/{category}"


@pytest.mark.parametrize("dealer_group_id", list_available_dealer_groups())
@pytest.mark.parametrize("category", CATEGORY_IDS)
async def test_citations_never_cross_dealer_groups(dealer_group_id: str, category: str) -> None:
    bundle = await FixtureEvidenceRetriever().retrieve(
        EvidenceRequest(dealer_group_id=dealer_group_id, category=category, detected_need_hint="")
    )
    assert all(c.dealer_group_id == dealer_group_id for c in bundle.citations)
