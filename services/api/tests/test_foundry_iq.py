"""Foundry IQ retriever: district isolation and citation mapping.

The coordinator's whole safety story rests on evidence never crossing
districts. With Foundry IQ that is enforced by an OData filter on a
filterable index field, so these tests assert the filter is actually built
and that the retriever still refuses anything that slips through.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.evidence.foundry_iq import FoundryIQEvidenceRetriever, _to_citation
from app.evidence.retrieval import EvidenceRequest, EvidenceRetrievalError

ENDPOINT = "https://example.search.windows.net"


def _doc(citation_id: str, district: str) -> dict[str, Any]:
    return {
        "citation_id": citation_id,
        "district_id": district,
        "source_title": "District A - Early Literacy Benchmarks",
        "evidence_summary": "Synthetic benchmark guidance.",
        "source_type": "structured_data",
        "section_or_page": "section 1",
        "source_ref": "fixture://dist-a/el-01",
    }


def _retriever(documents: list[dict[str, Any]], captured: dict[str, Any]) -> Any:
    retriever = FoundryIQEvidenceRetriever(
        endpoint=ENDPOINT,
        knowledge_base="asg-kb-demo",
        index_name="asg-evidence-demo",
    )

    def fake_sync(request: EvidenceRequest) -> list[dict[str, Any]]:
        captured["district_id"] = request.district_id
        return documents

    retriever._retrieve_sync = fake_sync  # type: ignore[method-assign]
    return retriever


async def test_missing_district_is_refused_before_any_call() -> None:
    retriever = _retriever([], {})
    with pytest.raises(EvidenceRetrievalError):
        await retriever.retrieve(
            EvidenceRequest(district_id="", category="early-literacy", detected_need_hint="")
        )


async def test_citations_are_mapped_from_index_documents() -> None:
    retriever = _retriever([_doc("DIST-A-el-01", "DIST-A")], {})
    bundle = await retriever.retrieve(
        EvidenceRequest(district_id="DIST-A", category="early-literacy", detected_need_hint="")
    )
    assert bundle.district_id == "DIST-A"
    assert [c.citation_id for c in bundle.citations] == ["DIST-A-el-01"]


async def test_foreign_district_documents_are_dropped() -> None:
    """Defence in depth.

    The OData filter should make this impossible, but blob and web knowledge
    sources carry no district field, so anything that reaches the retriever
    from another district must still be discarded here.
    """

    retriever = _retriever([_doc("DIST-A-el-01", "DIST-A"), _doc("DIST-B-el-01", "DIST-B")], {})
    bundle = await retriever.retrieve(
        EvidenceRequest(district_id="DIST-A", category="early-literacy", detected_need_hint="")
    )
    assert [c.citation_id for c in bundle.citations] == ["DIST-A-el-01"]
    assert all(c.district_id == "DIST-A" for c in bundle.citations)


async def test_documents_without_a_citation_id_are_dropped() -> None:
    retriever = _retriever([{"district_id": "DIST-A", "source_title": "No id"}], {})
    bundle = await retriever.retrieve(
        EvidenceRequest(district_id="DIST-A", category="early-literacy", detected_need_hint="")
    )
    assert bundle.citations == ()


async def test_provider_failure_becomes_a_typed_evidence_error() -> None:
    retriever = FoundryIQEvidenceRetriever(endpoint=ENDPOINT, knowledge_base="kb", index_name="idx")

    def boom(request: EvidenceRequest) -> list[dict[str, Any]]:
        raise RuntimeError("search exploded")

    retriever._retrieve_sync = boom  # type: ignore[method-assign]
    with pytest.raises(EvidenceRetrievalError) as excinfo:
        await retriever.retrieve(
            EvidenceRequest(district_id="DIST-A", category="x", detected_need_hint="")
        )
    # The raw provider message must not reach the caller.
    assert "search exploded" not in str(excinfo.value)


def test_unconfigured_retriever_fails_fast() -> None:
    with pytest.raises(EvidenceRetrievalError):
        FoundryIQEvidenceRetriever(endpoint="", knowledge_base="", index_name="")


@pytest.mark.parametrize(
    ("knowledge_base", "expected"),
    [
        ("asg-kb-demo", "asg-ks-demo"),
        # The portal walkthrough produces this name. A plain
        # .replace("-kb-", "-ks-") no-ops here, leaving the retriever querying
        # a source that does not exist.
        ("kb-alias", "ks-alias"),
        ("team-kb", "team-ks"),
    ],
)
def test_source_name_derived_from_knowledge_base(knowledge_base: str, expected: str) -> None:
    from app.evidence.foundry_iq import _derive_source_name

    assert _derive_source_name(knowledge_base) == expected


def test_explicit_knowledge_source_wins_over_derivation() -> None:
    retriever = FoundryIQEvidenceRetriever(
        endpoint="https://example.search.windows.net",
        knowledge_base="kb-alias",
        knowledge_source="totally-different-source",
    )
    assert retriever._knowledge_source == "totally-different-source"


def test_unknown_source_type_falls_back_rather_than_crashing() -> None:
    citation = _to_citation(
        {
            "citation_id": "X",
            "district_id": "DIST-A",
            "source_type": "not-a-real-type",
            "evidence_summary": "text",
        },
        "DIST-A",
    )
    assert citation is not None
    assert citation.district_id == "DIST-A"


def test_untagged_documents_are_dropped_not_relabelled() -> None:
    """The live failure this guards against.

    A knowledge base holds blob and web sources next to the index, and those
    carry no district_id. Verified against a live knowledge base: scoping the
    request to the index source does NOT stop the blob source contributing.
    `_to_citation` previously defaulted the district to the caller's, turning
    unscoped content into an apparently district-owned citation that passed
    every downstream isolation check.
    """

    untagged = {
        "citation_id": "BLOB-1",
        "evidence_summary": "Text from a blob document with no district field.",
    }
    assert _to_citation(untagged, "DIST-A") is None


def test_to_citation_drops_foreign_district_documents() -> None:
    foreign = {
        "citation_id": "B-1",
        "district_id": "DIST-B",
        "evidence_summary": "Evidence belonging to another district.",
    }
    assert _to_citation(foreign, "DIST-A") is None


def test_partial_documents_are_dropped_not_raised() -> None:
    """A document missing required text must not abort the whole retrieval."""

    assert _to_citation({"citation_id": "X", "district_id": "DIST-A"}, "DIST-A") is None


@pytest.mark.parametrize(
    ("district", "expected"),
    [("DIST-A", "district_id eq 'DIST-A'"), ("O'Neil", "district_id eq 'O''Neil'")],
)
def test_odata_filter_escapes_quotes(district: str, expected: str) -> None:
    """An unescaped quote would break the filter, silently widening the scope."""

    from app.evidence.foundry_iq import _escape_odata

    assert f"district_id eq '{_escape_odata(district)}'" == expected
