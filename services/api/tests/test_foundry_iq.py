"""Foundry IQ retriever: dealer group isolation and citation mapping.

The coordinator's whole safety story rests on evidence never crossing
dealer groups. With Foundry IQ that is enforced by an OData filter on a
filterable index field, so these tests assert the filter is actually built
and that the retriever still refuses anything that slips through.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.evidence.foundry_iq import FoundryIQEvidenceRetriever, _to_citation
from app.evidence.retrieval import EvidenceRequest, EvidenceRetrievalError

ENDPOINT = "https://example.search.windows.net"


def _doc(citation_id: str, group: str) -> dict[str, Any]:
    return {
        "citation_id": citation_id,
        "dealer_group_id": group,
        "source_title": "Group A - Enquiry Response Benchmarks",
        "evidence_summary": "Synthetic benchmark guidance.",
        "source_type": "structured_data",
        "section_or_page": "section 1",
        "source_ref": "fixture://group-a/lr-01",
    }


def _retriever(documents: list[dict[str, Any]], captured: dict[str, Any]) -> Any:
    retriever = FoundryIQEvidenceRetriever(
        endpoint=ENDPOINT,
        knowledge_base="asg-kb-demo",
    )

    def fake_sync(request: EvidenceRequest) -> list[dict[str, Any]]:
        captured["dealer_group_id"] = request.dealer_group_id
        return documents

    retriever._retrieve_sync = fake_sync  # type: ignore[method-assign]
    return retriever


async def test_missing_dealer_group_is_refused_before_any_call() -> None:
    retriever = _retriever([], {})
    with pytest.raises(EvidenceRetrievalError):
        await retriever.retrieve(
            EvidenceRequest(dealer_group_id="", category="lead-response", detected_need_hint="")
        )


async def test_citations_are_mapped_from_index_documents() -> None:
    retriever = _retriever([_doc("GROUP-A-el-01", "GROUP-A")], {})
    bundle = await retriever.retrieve(
        EvidenceRequest(dealer_group_id="GROUP-A", category="lead-response", detected_need_hint="")
    )
    assert bundle.dealer_group_id == "GROUP-A"
    assert [c.citation_id for c in bundle.citations] == ["GROUP-A-el-01"]


async def test_foreign_dealer_group_documents_are_dropped() -> None:
    """Defence in depth.

    The OData filter should make this impossible, but blob and web knowledge
    sources carry no dealer group field, so anything that reaches the retriever
    from another dealer group must still be discarded here.
    """

    retriever = _retriever([_doc("GROUP-A-el-01", "GROUP-A"), _doc("GROUP-B-el-01", "GROUP-B")], {})
    bundle = await retriever.retrieve(
        EvidenceRequest(dealer_group_id="GROUP-A", category="lead-response", detected_need_hint="")
    )
    assert [c.citation_id for c in bundle.citations] == ["GROUP-A-el-01"]
    assert all(c.dealer_group_id == "GROUP-A" for c in bundle.citations)


async def test_documents_without_a_citation_id_are_dropped() -> None:
    retriever = _retriever([{"dealer_group_id": "GROUP-A", "source_title": "No id"}], {})
    bundle = await retriever.retrieve(
        EvidenceRequest(dealer_group_id="GROUP-A", category="lead-response", detected_need_hint="")
    )
    assert bundle.citations == ()


async def test_provider_failure_becomes_a_typed_evidence_error() -> None:
    retriever = FoundryIQEvidenceRetriever(endpoint=ENDPOINT, knowledge_base="kb")

    def boom(request: EvidenceRequest) -> list[dict[str, Any]]:
        raise RuntimeError("search exploded")

    retriever._retrieve_sync = boom  # type: ignore[method-assign]
    with pytest.raises(EvidenceRetrievalError) as excinfo:
        await retriever.retrieve(
            EvidenceRequest(dealer_group_id="GROUP-A", category="x", detected_need_hint="")
        )
    # The raw provider message must not reach the caller.
    assert "search exploded" not in str(excinfo.value)


def test_unconfigured_retriever_fails_fast() -> None:
    with pytest.raises(EvidenceRetrievalError):
        FoundryIQEvidenceRetriever(endpoint="", knowledge_base="")


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
            "dealer_group_id": "GROUP-A",
            "source_type": "not-a-real-type",
            "evidence_summary": "text",
        },
        "GROUP-A",
    )
    assert citation is not None
    assert citation.dealer_group_id == "GROUP-A"


def test_untagged_documents_are_dropped_not_relabelled() -> None:
    """The live failure this guards against.

    A knowledge base holds blob and web sources next to the index, and those
    carry no dealer_group_id. Verified against a live knowledge base: scoping the
    request to the index source does NOT stop the blob source contributing.
    `_to_citation` previously defaulted the dealer group to the caller's, turning
    unscoped content into an apparently dealer group-owned citation that passed
    every downstream isolation check.
    """

    untagged = {
        "citation_id": "BLOB-1",
        "evidence_summary": "Text from a blob document with no dealer group field.",
    }
    assert _to_citation(untagged, "GROUP-A") is None


def test_to_citation_drops_foreign_dealer_group_documents() -> None:
    foreign = {
        "citation_id": "B-1",
        "dealer_group_id": "GROUP-B",
        "evidence_summary": "Evidence belonging to another dealer group.",
    }
    assert _to_citation(foreign, "GROUP-A") is None


def test_partial_documents_are_dropped_not_raised() -> None:
    """A document missing required text must not abort the whole retrieval."""

    assert _to_citation({"citation_id": "X", "dealer_group_id": "GROUP-A"}, "GROUP-A") is None


@pytest.mark.parametrize(
    ("group", "expected"),
    [("GROUP-A", "dealer_group_id eq 'GROUP-A'"), ("O'Neil", "dealer_group_id eq 'O''Neil'")],
)
def test_odata_filter_escapes_quotes(group: str, expected: str) -> None:
    """An unescaped quote would break the filter, silently widening the scope."""

    from app.evidence.foundry_iq import _escape_odata

    assert f"dealer_group_id eq '{_escape_odata(group)}'" == expected
