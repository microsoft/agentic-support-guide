"""Tests proving dealer group A requests can never see dealer group B evidence."""

from __future__ import annotations

import pytest

from app.agents.shared.contracts import Citation, CitationSourceType
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from app.evidence import EvidenceRequest, FixtureEvidenceRetriever
from app.evidence.fixtures import list_available_dealer_groups

from .conftest import (
    DEFAULT_DEALER_GROUP,
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
)
from .fakes import FakeChatClientFactory, make_fake_runtime
from .test_agents import _analyst_ctx, _bundle  # reuse helpers


async def test_fixture_retriever_never_returns_other_dealer_groups() -> None:
    retriever = FixtureEvidenceRetriever()
    for group in list_available_dealer_groups():
        bundle = await retriever.retrieve(
            EvidenceRequest(dealer_group_id=group, category="lead-response", detected_need_hint="")
        )
        for c in bundle.citations:
            assert c.dealer_group_id == group, (
                f"retriever leaked a citation from {c.dealer_group_id} into request for {group}"
            )


async def test_fixture_retriever_returns_empty_for_unknown_category() -> None:
    retriever = FixtureEvidenceRetriever()
    bundle = await retriever.retrieve(
        EvidenceRequest(
            dealer_group_id="GROUP-DEMO",
            category="__does_not_exist__",
            detected_need_hint="",
        )
    )
    assert bundle.citations == ()


async def test_two_dealer_groups_receive_different_citations() -> None:
    retriever = FixtureEvidenceRetriever()
    a = await retriever.retrieve(
        EvidenceRequest(dealer_group_id="GROUP-A", category="lead-response", detected_need_hint="")
    )
    b = await retriever.retrieve(
        EvidenceRequest(dealer_group_id="GROUP-B", category="lead-response", detected_need_hint="")
    )
    a_ids = {c.citation_id for c in a.citations}
    b_ids = {c.citation_id for c in b.citations}
    assert a_ids.isdisjoint(b_ids)


async def test_validator_rejects_cross_dealer_group_citation() -> None:
    """Draft carries a GROUP-B citation for a GROUP-A request - must fail."""

    from app.agents.data_analyst import DataAnalystAgent
    from app.agents.support_recommender import (
        SupportRecommendationAgent,
        SupportRecommenderContext,
    )

    client = FakeChatClientFactory()
    client.register_response("data-analyst-agent", canned_data_analyst_output())
    client.register_response(
        "support-recommendation-agent",
        canned_recommendation_draft(
            goal_ids=["GOAL-lead-response-1"],
            strategy_ids=["ST-lead-response-1"],
        ),
    )
    client.register_response("validator-agent", canned_validator_critique())
    runtime, _ = make_fake_runtime(client)

    retriever = FixtureEvidenceRetriever()
    dist_b_bundle = await retriever.retrieve(
        EvidenceRequest(dealer_group_id="GROUP-B", category="lead-response", detected_need_hint="")
    )
    ctx = SupportRecommenderContext(
        dealer_group_id="GROUP-A",  # Request dealer group
        category="lead-response",
        concern_text="synthetic",
        allowed_resources=(),
        allowed_goal_ids=("GOAL-lead-response-1",),
        allowed_strategy_ids=("ST-lead-response-1",),
        evidence=dist_b_bundle,  # But bundle is from GROUP-B (illegal)
    )
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, ctx)
    # The wrapper resolves cited_ids against the supplied bundle, so a model
    # can no longer smuggle in another dealer group's citation. Attach one
    # directly to prove the validator still catches it defensively.
    draft = draft.model_copy(update={"citations": list(dist_b_bundle.citations)})
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id="GROUP-A",
                allowed_resource_ids=(),
                allowed_goal_ids=("GOAL-lead-response-1",),
                allowed_strategy_ids=("ST-lead-response-1",),
                allowed_citation_ids=tuple(c.citation_id for c in dist_b_bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "CROSS_DEALER_GROUP_CITATION" in report.issue_codes
    assert "citations" in report.failed_fields


async def test_validator_rejects_unknown_source_ref() -> None:
    """Draft carries a citation whose citation_id is not in allowed set."""

    from datetime import UTC, datetime

    client = FakeChatClientFactory()
    client.register_response("validator-agent", canned_validator_critique())
    runtime, _ = make_fake_runtime(client)
    # Build a synthetic draft directly to bypass wrapper attaching citations.
    from app.agents.shared.contracts import (
        AnalysisSummary,
        DataAnalystOutput,
        SupportRecommendationDraft,
    )

    fake_c = Citation(
        citation_id="FAKE-INVENTED",
        dealer_group_id=DEFAULT_DEALER_GROUP,
        source_type=CitationSourceType.SYNTHETIC_FIXTURE,
        source_title="Invented",
        section_or_page="",
        evidence_summary="Not in allowed set.",
        source_ref="fixture://demo/invented",
        retrieved_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        confidence=0.5,
    )
    draft = SupportRecommendationDraft(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        detected_need="synthetic",
        support_tier="Focused support",
        recommended_frequency="3x weekly",
        grouping_guidance="small group",
        resource_ids=[],
        rationale="synthetic",
        goal_suggestions=[],
        strategy_suggestions=[],
        manager_next_steps=["Confirm baseline."],
        progress_monitoring=["Weekly probe."],
        review_window_days=28,
        decision_rule="IF baseline low THEN targeted.",
        caveats=["Human review is required before any decision."],
        citations=[fake_c],
    )
    analysis = DataAnalystOutput(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        analysis=AnalysisSummary(
            detected_need="n", evidence_bullets=[], missing_data_flags=[], analysis_confidence=0.5
        ),
    )
    real_bundle = await _bundle()
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=(),
                allowed_strategy_ids=(),
                allowed_citation_ids=tuple(c.citation_id for c in real_bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "UNKNOWN_CITATION_ID" in report.issue_codes


async def test_recommendation_request_requires_dealer_group_id() -> None:
    """The API-level Pydantic model refuses missing dealer_group_id."""

    from pydantic import ValidationError

    from app.models import SupportPlanRequest

    with pytest.raises(ValidationError):
        SupportPlanRequest(
            dealership_id="DLR-0001",
            category="lead-response",
            concern_text="Median first response to online enquiries slipped past one hour.",
        )  # type: ignore[call-arg]
