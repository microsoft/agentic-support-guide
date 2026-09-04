"""Every category the UI can offer must have evidence in every district.

The recommendation contract requires at least one citation, so a category
with no fixtures can never produce a valid plan - it fails at protocol
validation instead. This test makes that gap loud.
"""

from __future__ import annotations

import pytest

from app.evidence.fixtures import FixtureEvidenceRetriever, list_available_districts
from app.evidence.retrieval import EvidenceRequest
from app.mock_data import CATEGORY_IDS


@pytest.mark.parametrize("district_id", list_available_districts())
@pytest.mark.parametrize("category", CATEGORY_IDS)
async def test_every_district_has_evidence_for_every_category(
    district_id: str, category: str
) -> None:
    bundle = await FixtureEvidenceRetriever().retrieve(
        EvidenceRequest(district_id=district_id, category=category, detected_need_hint="")
    )
    assert bundle.citations, f"no evidence fixtures for {district_id}/{category}"


@pytest.mark.parametrize("district_id", list_available_districts())
@pytest.mark.parametrize("category", CATEGORY_IDS)
async def test_citations_never_cross_districts(district_id: str, category: str) -> None:
    bundle = await FixtureEvidenceRetriever().retrieve(
        EvidenceRequest(district_id=district_id, category=category, detected_need_hint="")
    )
    assert all(c.district_id == district_id for c in bundle.citations)
