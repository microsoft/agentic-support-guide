"""Tests proving district A requests can never see district B evidence."""

from __future__ import annotations

import pytest

from app.agents.shared.contracts import Citation, CitationSourceType
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from app.evidence import EvidenceRequest, FixtureEvidenceRetriever
from app.evidence.fixtures import list_available_districts

from .conftest import (
    DEFAULT_DISTRICT,
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
)
from .fakes import FakeFoundryClient, build_bindings, make_fake_adapter
from .test_agents import _analyst_ctx, _bundle  # reuse helpers


def test_fixture_retriever_never_returns_other_districts() -> None:
    retriever = FixtureEvidenceRetriever()
    for district in list_available_districts():
        bundle = retriever.retrieve(
            EvidenceRequest(district_id=district, category="early-literacy", detected_need_hint="")
        )
        for c in bundle.citations:
            assert (
                c.district_id == district
            ), f"retriever leaked a citation from {c.district_id} into request for {district}"


def test_fixture_retriever_returns_empty_for_unknown_category() -> None:
    retriever = FixtureEvidenceRetriever()
    bundle = retriever.retrieve(
        EvidenceRequest(
            district_id="DIST-DEMO",
            category="__does_not_exist__",
            detected_need_hint="",
        )
    )
    assert bundle.citations == ()


def test_two_districts_receive_different_citations() -> None:
    retriever = FixtureEvidenceRetriever()
    a = retriever.retrieve(
        EvidenceRequest(district_id="DIST-A", category="early-literacy", detected_need_hint="")
    )
    b = retriever.retrieve(
        EvidenceRequest(district_id="DIST-B", category="early-literacy", detected_need_hint="")
    )
    a_ids = {c.citation_id for c in a.citations}
    b_ids = {c.citation_id for c in b.citations}
    assert a_ids.isdisjoint(b_ids)


def test_validator_rejects_cross_district_citation() -> None:
    """Draft carries a DIST-B citation for a DIST-A request - must fail."""

    from app.agents.data_analyst import DataAnalystAgent
    from app.agents.support_recommender import (
        SupportRecommendationAgent,
        SupportRecommenderContext,
    )

    client = FakeFoundryClient()
    bindings = build_bindings()
    client.register_response(
        bindings["data-analyst-agent"].assistant_id, canned_data_analyst_output()
    )
    client.register_response(
        bindings["support-recommendation-agent"].assistant_id,
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    client.register_response(bindings["validator-agent"].assistant_id, canned_validator_critique())
    adapter = make_fake_adapter(client)

    retriever = FixtureEvidenceRetriever()
    dist_b_bundle = retriever.retrieve(
        EvidenceRequest(district_id="DIST-B", category="early-literacy", detected_need_hint="")
    )
    ctx = SupportRecommenderContext(
        district_id="DIST-A",  # Request district
        category="early-literacy",
        sanitized_concern_text="synthetic",
        allowed_resources=(),
        allowed_smart_goal_ids=("SG-early-literacy-1",),
        allowed_strategy_ids=("ST-early-literacy-1",),
        evidence=dist_b_bundle,  # But bundle is from DIST-B (illegal)
    )
    analysis = DataAnalystAgent(adapter).analyze(_analyst_ctx())
    draft = SupportRecommendationAgent(adapter).recommend(analysis, ctx)
    # Draft district_id gets set to context.district_id ("DIST-A") by wrapper.
    # But the citations carry district_id=DIST-B.
    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id="DIST-A",
                allowed_resource_ids=(),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                allowed_citation_ids=tuple(c.citation_id for c in dist_b_bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "CROSS_DISTRICT_CITATION" in report.issue_codes
    assert "citations" in report.failed_fields


def test_validator_rejects_unknown_source_ref() -> None:
    """Draft carries a citation whose citation_id is not in allowed set."""

    from datetime import UTC, datetime

    client = FakeFoundryClient()
    bindings = build_bindings()
    client.register_response(bindings["validator-agent"].assistant_id, canned_validator_critique())
    adapter = make_fake_adapter(client)
    # Build a synthetic draft directly to bypass wrapper attaching citations.
    from app.agents.shared.contracts import (
        AnalysisSummary,
        DataAnalystOutput,
        SupportRecommendationDraft,
    )

    fake_c = Citation(
        citation_id="FAKE-INVENTED",
        district_id=DEFAULT_DISTRICT,
        source_type=CitationSourceType.SYNTHETIC_FIXTURE,
        source_title="Invented",
        section_or_page="",
        evidence_summary="Not in allowed set.",
        source_ref="fixture://demo/invented",
        retrieved_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        confidence=0.5,
    )
    draft = SupportRecommendationDraft(
        district_id=DEFAULT_DISTRICT,
        detected_need="synthetic",
        support_tier="Targeted support",
        recommended_frequency="3x weekly",
        grouping_guidance="small group",
        resource_ids=[],
        rationale="synthetic",
        smart_goal_suggestions=[],
        strategy_suggestions=[],
        educator_next_steps=["Confirm baseline."],
        progress_monitoring=["Weekly probe."],
        review_window_days=28,
        decision_rule="IF baseline low THEN targeted.",
        caveats=["Human review is required before any decision."],
        citations=[fake_c],
    )
    analysis = DataAnalystOutput(
        district_id=DEFAULT_DISTRICT,
        analysis=AnalysisSummary(
            detected_need="n", evidence_bullets=[], missing_data_flags=[], analysis_confidence=0.5
        ),
    )
    real_bundle = _bundle()
    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id=DEFAULT_DISTRICT,
                allowed_resource_ids=(),
                allowed_smart_goal_ids=(),
                allowed_strategy_ids=(),
                allowed_citation_ids=tuple(c.citation_id for c in real_bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "UNKNOWN_CITATION_ID" in report.issue_codes


def test_recommendation_request_requires_district_id() -> None:
    """The API-level Pydantic model refuses missing district_id."""

    from pydantic import ValidationError

    from app.models import SupportPlanRequest

    with pytest.raises(ValidationError):
        SupportPlanRequest(
            learner_id="LRN-0001",
            category="early-literacy",
            concern_text="Letter-sound fluency below expected pace.",
        )  # type: ignore[call-arg]
