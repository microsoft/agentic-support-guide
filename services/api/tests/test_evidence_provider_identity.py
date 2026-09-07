"""The agent trace must name the real evidence provider.

The provider and model were hardcoded to "fixture"/"synthetic", so a run
grounded by Foundry IQ still reported fixtures. That makes the trace
useless for the one question it exists to answer: was this answer grounded?
"""

from __future__ import annotations

from app.evidence.fixtures import FixtureEvidenceRetriever
from app.evidence.retrieval import EvidenceRetriever


def test_fixture_retriever_declares_itself() -> None:
    retriever = FixtureEvidenceRetriever()
    assert retriever.provider_name == "fixture"
    assert retriever.provider_model == "synthetic"


def test_foundry_iq_retriever_declares_itself() -> None:
    from app.evidence.foundry_iq import FoundryIQEvidenceRetriever

    retriever = FoundryIQEvidenceRetriever(
        endpoint="https://example.search.windows.net",
        knowledge_base="kb-under-test",
        index_name="idx-under-test",
    )
    assert retriever.provider_name == "foundry_iq"
    assert retriever.provider_model == "kb-under-test"


def test_both_retrievers_satisfy_the_protocol() -> None:
    from app.evidence.foundry_iq import FoundryIQEvidenceRetriever

    fixture: EvidenceRetriever = FixtureEvidenceRetriever()
    foundry: EvidenceRetriever = FoundryIQEvidenceRetriever(
        endpoint="https://example.search.windows.net",
        knowledge_base="kb-under-test",
        index_name="idx-under-test",
    )
    assert fixture.provider_name != foundry.provider_name
