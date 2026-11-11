"""Synthetic per-dealer-group evidence fixtures.

Every entry is deterministic and generic. Nothing here references real
customer, group, dealership, staff, or document names. Groups are named
`GROUP-A`, `GROUP-B`, and `GROUP-DEMO` to reinforce that these are
placeholders.

A dealer group is an ownership boundary, not a franchise brand, so two
groups selling the same brand must never see each other's evidence.

Production replacement: a Fabric-backed retriever that reads from the
per-group lakehouse and optionally the group's approved document library.
That retriever should keep the same interface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..agents.shared.contracts import Citation, CitationSourceType
from .retrieval import (
    CrossDealerGroupEvidenceError,
    EvidenceBundle,
    EvidenceRequest,
    EvidenceRetrievalError,
)


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fixture(
    group: str,
    cid: str,
    kind: CitationSourceType,
    title: str,
    summary: str,
) -> Citation:
    return Citation(
        citation_id=f"{group}-{cid}",
        dealer_group_id=group,
        source_type=kind,
        source_title=title,
        section_or_page="section 1",
        evidence_summary=summary,
        source_ref=f"fixture://{group.lower()}/{cid}",
        retrieved_at=_iso_now(),
        confidence=0.8,
    )


_DEALER_GROUPS: dict[str, dict[str, list[Citation]]] = {
    "GROUP-A": {
        "lead-response": [
            _fixture(
                "GROUP-A",
                "lead-01",
                CitationSourceType.STRUCTURED_DATA,
                "Group A - Enquiry Response Benchmarks",
                (
                    "Synthetic benchmark describing the expected first-response window "
                    "for the current review period."
                ),
            ),
            _fixture(
                "GROUP-A",
                "lead-02",
                CitationSourceType.RESOURCE,
                "Group A - Approved Enquiry Handling Routines",
                (
                    "Synthetic resource catalog entry describing an allowed daily "
                    "enquiry triage routine."
                ),
            ),
        ],
        "test-drive-conversion": [
            _fixture(
                "GROUP-A",
                "drive-01",
                CitationSourceType.POLICY,
                "Group A - Test Drive Booking Standard",
                "Synthetic policy summary describing confirmation and preparation steps.",
            ),
        ],
        "listing-completeness": [
            _fixture(
                "GROUP-A",
                "listing-01",
                CitationSourceType.POLICY,
                "Group A - Listing Publication Checklist",
                (
                    "Synthetic checklist describing the photo and specification fields "
                    "required before a listing publishes."
                ),
            ),
        ],
        "inventory-ageing": [
            _fixture(
                "GROUP-A",
                "ageing-01",
                CitationSourceType.STRUCTURED_DATA,
                "Group A - Inventory Review Cadence",
                (
                    "Synthetic reference describing how often each vehicle is reviewed "
                    "and who signs the review off."
                ),
            ),
        ],
        "price-data-freshness": [
            _fixture(
                "GROUP-A",
                "price-01",
                CitationSourceType.POLICY,
                "Group A - Advertised Price Refresh Standard",
                "Synthetic policy summary describing the price refresh cadence and owner.",
            ),
        ],
        "multi-area": [
            _fixture(
                "GROUP-A",
                "multi-01",
                CitationSourceType.POLICY,
                "Group A - Coordinated Process Review Policy",
                (
                    "Synthetic policy summary describing how enquiry handling, test "
                    "drives, and listing quality are reviewed in one plan."
                ),
            ),
        ],
    },
    "GROUP-B": {
        "lead-response": [
            _fixture(
                "GROUP-B",
                "lead-01",
                CitationSourceType.DOCUMENT,
                "Group B - Enquiry Handling Handbook",
                (
                    "Synthetic handbook excerpt describing response-time expectations "
                    "by enquiry channel."
                ),
            ),
        ],
        "test-drive-conversion": [
            _fixture(
                "GROUP-B",
                "drive-01",
                CitationSourceType.DOCUMENT,
                "Group B - Test Drive Handbook",
                "Synthetic handbook excerpt describing rebooking after a no-show.",
            ),
        ],
        "listing-completeness": [
            _fixture(
                "GROUP-B",
                "listing-01",
                CitationSourceType.DOCUMENT,
                "Group B - Listing Standards Handbook",
                "Synthetic handbook excerpt describing the required listing field set.",
            ),
        ],
        "inventory-ageing": [
            _fixture(
                "GROUP-B",
                "ageing-01",
                CitationSourceType.RESOURCE,
                "Group B - Approved Review Cadence Catalog",
                "Synthetic resource catalog entry describing allowed review routines.",
            ),
        ],
        "price-data-freshness": [
            _fixture(
                "GROUP-B",
                "price-01",
                CitationSourceType.DOCUMENT,
                "Group B - Price Data Handbook",
                "Synthetic handbook excerpt describing the price refresh exception report.",
            ),
        ],
        "multi-area": [
            _fixture(
                "GROUP-B",
                "multi-01",
                CitationSourceType.DOCUMENT,
                "Group B - Coordinated Improvement Handbook",
                "Synthetic handbook excerpt describing coordinated multi-area planning.",
            ),
        ],
    },
    "GROUP-DEMO": {
        "lead-response": [
            _fixture(
                "GROUP-DEMO",
                "lead-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Enquiry Response Benchmarks",
                "Synthetic benchmark describing the expected first-response window for online "
                "enquiries and the median response time recorded this review period.",
            ),
            _fixture(
                "GROUP-DEMO",
                "lead-02",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Follow-up Monitoring Guide",
                "Synthetic guide describing a weekly follow-up cadence for unanswered enquiries "
                "and how leads awaiting a reply are escalated.",
            ),
        ],
        "test-drive-conversion": [
            _fixture(
                "GROUP-DEMO",
                "drive-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Test Drive Conversion Notes",
                "Synthetic notes describing how booked test drive appointments are confirmed "
                "and how attendance converts to completed sales conversations.",
            ),
        ],
        "listing-completeness": [
            _fixture(
                "GROUP-DEMO",
                "listing-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Listing Completeness Standard",
                "Synthetic standard describing the photographs, specification fields, and "
                "pricing detail a vehicle listing must carry before publication.",
            ),
        ],
        "inventory-ageing": [
            _fixture(
                "GROUP-DEMO",
                "ageing-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Inventory Ageing Review",
                "Synthetic review describing how ageing stock is identified by days in "
                "inventory and how on-time review cadence is tracked.",
            ),
        ],
        "price-data-freshness": [
            _fixture(
                "GROUP-DEMO",
                "price-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Price Data Freshness Policy",
                "Synthetic policy describing how often advertised price data is refreshed "
                "against market guidance and what counts as stale pricing.",
            ),
        ],
        "multi-area": [
            _fixture(
                "GROUP-DEMO",
                "multi-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo group - Coordinated Review Policy",
                "Synthetic policy summary describing how enquiry handling, test drives, and "
                "listing quality are reviewed together rather than area by area.",
            ),
        ],
    },
}


def list_available_dealer_groups() -> tuple[str, ...]:
    return tuple(sorted(_DEALER_GROUPS.keys()))


class FixtureEvidenceRetriever:
    """Synthetic-only retriever, keyed strictly by dealer_group_id."""

    provider_name = "fixture"
    provider_model = "synthetic"
    evidence_verifiable = True

    def __init__(self, catalog: dict[str, dict[str, list[Citation]]] | None = None) -> None:
        self._catalog = catalog if catalog is not None else _DEALER_GROUPS

    def has_dealer_group(self, dealer_group_id: str) -> bool:
        return dealer_group_id in self._catalog

    async def retrieve(self, request: EvidenceRequest) -> EvidenceBundle:
        if not request.dealer_group_id:
            raise EvidenceRetrievalError(
                "MISSING_DEALER_GROUP_ID",
                "Evidence request is missing a dealer_group_id.",
            )
        if request.dealer_group_id not in self._catalog:
            raise EvidenceRetrievalError(
                "UNKNOWN_DEALER_GROUP",
                f"No synthetic evidence configured for group '{request.dealer_group_id}'.",
            )
        by_category = self._catalog[request.dealer_group_id]
        items = list(by_category.get(request.category, ()))
        # Defensive: refuse to return any item whose group tag disagrees.
        for c in items:
            if c.dealer_group_id != request.dealer_group_id:
                raise CrossDealerGroupEvidenceError(
                    "CROSS_DEALER_GROUP_CITATION",
                    "Fixture returned a citation from a different dealer group.",
                )
        if request.max_items > 0:
            items = items[: request.max_items]
        return EvidenceBundle(
            dealer_group_id=request.dealer_group_id,
            citations=tuple(items),
        )
