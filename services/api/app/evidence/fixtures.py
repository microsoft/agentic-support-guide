"""Synthetic per-district evidence fixtures.

Every entry is deterministic and generic. Nothing here references real
customer, district, school, staff, or document names. Districts are
named `DIST-A`, `DIST-B`, and `DIST-DEMO` to reinforce that these are
placeholders.

Production replacement: a Fabric-backed retriever that reads from the
per-district lakehouse and optionally the district's approved PDF
library. That retriever should keep the same interface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..agents.shared.contracts import Citation, CitationSourceType
from .retrieval import (
    CrossDistrictEvidenceError,
    EvidenceBundle,
    EvidenceRequest,
    EvidenceRetrievalError,
)


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fixture(
    district: str,
    cid: str,
    kind: CitationSourceType,
    title: str,
    summary: str,
) -> Citation:
    return Citation(
        citation_id=f"{district}-{cid}",
        district_id=district,
        source_type=kind,
        source_title=title,
        section_or_page="section 1",
        evidence_summary=summary,
        source_ref=f"fixture://{district.lower()}/{cid}",
        retrieved_at=_iso_now(),
        confidence=0.8,
    )


_DISTRICTS: dict[str, dict[str, list[Citation]]] = {
    "DIST-A": {
        "early-literacy": [
            _fixture(
                "DIST-A",
                "el-01",
                CitationSourceType.STRUCTURED_DATA,
                "District A - Early Literacy Benchmarks",
                (
                    "Synthetic benchmark points to a targeted letter-sound intervention plan "
                    "for the current review window."
                ),
            ),
            _fixture(
                "DIST-A",
                "el-02",
                CitationSourceType.RESOURCE,
                "District A - Approved Phonemic Awareness Routines",
                (
                    "Synthetic resource catalog entry describing an allowed daily phonemic "
                    "awareness routine."
                ),
            ),
        ],
        "reading-below-grade": [
            _fixture(
                "DIST-A",
                "rbg-01",
                CitationSourceType.POLICY,
                "District A - Reading Support Tier Policy",
                "Synthetic policy summary describing how targeted reading support is authorized.",
            ),
        ],
        "attendance-support": [
            _fixture(
                "DIST-A",
                "att-01",
                CitationSourceType.POLICY,
                "District A - Attendance Intervention Policy",
                (
                    "Synthetic policy summary describing the attendance thresholds that "
                    "trigger a check-in routine."
                ),
            ),
        ],
        "math-acceleration": [
            _fixture(
                "DIST-A",
                "math-01",
                CitationSourceType.STRUCTURED_DATA,
                "District A - Math Enrichment Benchmarks",
                (
                    "Synthetic benchmark points to enrichment planning for learners "
                    "exceeding grade-level checks."
                ),
            ),
        ],
        "multi-domain": [
            _fixture(
                "DIST-A",
                "md-01",
                CitationSourceType.POLICY,
                "District A - Multi-Domain Support Coordination Policy",
                (
                    "Synthetic policy summary describing how supports across literacy, "
                    "math, and attendance are coordinated in one plan."
                ),
            ),
        ],
    },
    "DIST-B": {
        "early-literacy": [
            _fixture(
                "DIST-B",
                "el-01",
                CitationSourceType.DOCUMENT,
                "District B - Early Literacy Handbook",
                (
                    "Synthetic handbook excerpt describing the district's small-group "
                    "early literacy model."
                ),
            ),
        ],
        "reading-below-grade": [
            _fixture(
                "DIST-B",
                "rbg-01",
                CitationSourceType.DOCUMENT,
                "District B - Reading Support Handbook",
                "Synthetic handbook excerpt describing tiered reading support entry criteria.",
            ),
        ],
        "attendance-support": [
            _fixture(
                "DIST-B",
                "att-01",
                CitationSourceType.DOCUMENT,
                "District B - Attendance Handbook",
                "Synthetic handbook excerpt describing the district's attendance outreach ladder.",
            ),
        ],
        "math-acceleration": [
            _fixture(
                "DIST-B",
                "math-01",
                CitationSourceType.RESOURCE,
                "District B - Approved Math Enrichment Catalog",
                "Synthetic resource catalog entry describing allowed math enrichment routines.",
            ),
        ],
        "multi-domain": [
            _fixture(
                "DIST-B",
                "md-01",
                CitationSourceType.DOCUMENT,
                "District B - Coordinated Supports Handbook",
                "Synthetic handbook excerpt describing coordinated multi-domain planning.",
            ),
        ],
    },
    "DIST-DEMO": {
        "early-literacy": [
            _fixture(
                "DIST-DEMO",
                "el-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo district - Early Literacy Fixture",
                "Illustrative synthetic reference used only for the customer demo.",
            ),
            _fixture(
                "DIST-DEMO",
                "el-02",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo district - Progress Monitoring Fixture",
                "Illustrative synthetic reference for a weekly probe cadence.",
            ),
        ],
        "reading-below-grade": [
            _fixture(
                "DIST-DEMO",
                "rbg-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo district - Reading Tier Fixture",
                "Illustrative synthetic reference for tiered reading support.",
            ),
        ],
        "attendance-support": [
            _fixture(
                "DIST-DEMO",
                "att-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo district - Attendance Fixture",
                "Illustrative synthetic reference for an attendance check-in routine.",
            ),
        ],
        "math-acceleration": [
            _fixture(
                "DIST-DEMO",
                "math-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo district - Math Enrichment Fixture",
                "Illustrative synthetic reference for enrichment planning.",
            ),
        ],
        "multi-domain": [
            _fixture(
                "DIST-DEMO",
                "md-01",
                CitationSourceType.SYNTHETIC_FIXTURE,
                "Demo district - Coordinated Supports Fixture",
                "Illustrative synthetic reference for coordinating supports across domains.",
            ),
        ],
    },
}


def list_available_districts() -> tuple[str, ...]:
    return tuple(sorted(_DISTRICTS.keys()))


class FixtureEvidenceRetriever:
    """Synthetic-only retriever, keyed strictly by district_id."""

    def __init__(self, catalog: dict[str, dict[str, list[Citation]]] | None = None) -> None:
        self._catalog = catalog if catalog is not None else _DISTRICTS

    def has_district(self, district_id: str) -> bool:
        return district_id in self._catalog

    async def retrieve(self, request: EvidenceRequest) -> EvidenceBundle:
        if not request.district_id:
            raise EvidenceRetrievalError(
                "MISSING_DISTRICT_ID",
                "Evidence request is missing a district_id.",
            )
        if request.district_id not in self._catalog:
            raise EvidenceRetrievalError(
                "UNKNOWN_DISTRICT",
                f"No synthetic evidence configured for district '{request.district_id}'.",
            )
        by_category = self._catalog[request.district_id]
        items = list(by_category.get(request.category, ()))
        # Defensive: refuse to return any item whose district tag disagrees.
        for c in items:
            if c.district_id != request.district_id:
                raise CrossDistrictEvidenceError(
                    "CROSS_DISTRICT_CITATION",
                    "Fixture returned a citation from a different district.",
                )
        if request.max_items > 0:
            items = items[: request.max_items]
        return EvidenceBundle(
            district_id=request.district_id,
            citations=tuple(items),
        )
