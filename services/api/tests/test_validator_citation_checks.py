from __future__ import annotations

from app.agents.data_analyst import DataAnalystAgent
from app.agents.support_recommender import SupportRecommendationAgent
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from app.evidence import EvidenceBundle

from .conftest import (
    DEFAULT_DEALER_GROUP,
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
)
from .fakes import FakeChatClientFactory, make_fake_runtime
from .test_agents import _analyst_ctx, _rec_ctx


def _seed(client: FakeChatClientFactory) -> None:
    client.register_response("data-analyst-agent", canned_data_analyst_output())
    client.register_response(
        "support-recommendation-agent",
        canned_recommendation_draft(
            goal_ids=["GOAL-lead-response-1"], strategy_ids=["ST-lead-response-1"]
        ),
    )
    client.register_response("validator-agent", canned_validator_critique())


async def _bundle_from_ctx() -> EvidenceBundle:
    return (await _rec_ctx()).evidence


async def test_validator_fails_on_missing_citations() -> None:
    """Empty citations list on the draft must trigger MISSING_CITATIONS."""

    from app.agents.support_recommender.agent import SupportRecommenderContext
    from app.evidence import EvidenceBundle

    client = FakeChatClientFactory()
    _seed(client)
    runtime, _ = make_fake_runtime(client)

    empty_bundle = EvidenceBundle(dealer_group_id=DEFAULT_DEALER_GROUP, citations=())
    ctx = SupportRecommenderContext(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        category="lead-response",
        concern_text="synthetic",
        allowed_resources=(),
        allowed_goal_ids=("GOAL-lead-response-1",),
        allowed_strategy_ids=("ST-lead-response-1",),
        evidence=empty_bundle,
    )
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, ctx)
    assert list(draft.citations) == []

    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=("GOAL-lead-response-1",),
                allowed_strategy_ids=("ST-lead-response-1",),
                allowed_citation_ids=(),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "MISSING_CITATIONS" in report.issue_codes
    assert "citations" in report.failed_fields
    assert report.safe_summary.startswith("Validator failed on:")


async def test_validator_flags_forbidden_determination_language() -> None:
    """Draft committing to a trade-in value must trigger FORBIDDEN_DETERMINATION."""

    from app.agents.shared.contracts import (
        AnalysisSummary,
        Citation,
        CitationSourceType,
        DataAnalystOutput,
        SupportRecommendationDraft,
    )

    citation = Citation(
        citation_id="GROUP-DEMO-el-01",
        dealer_group_id=DEFAULT_DEALER_GROUP,
        source_type=CitationSourceType.SYNTHETIC_FIXTURE,
        source_title="Fixture",
        section_or_page="",
        evidence_summary="synthetic",
        source_ref="fixture://demo/el-01",
        retrieved_at="2026-01-05T09:00:00Z",
        confidence=0.7,
    )
    draft = SupportRecommendationDraft(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        detected_need="synthetic",
        support_tier="Focused support",
        recommended_frequency="3x weekly",
        grouping_guidance="small group",
        resource_ids=[],
        rationale=(
            "The synthetic dealership should tell the customer their trade-in is worth $8,500."
        ),
        goal_suggestions=[],
        strategy_suggestions=[],
        manager_next_steps=["Confirm baseline."],
        progress_monitoring=["Weekly probe."],
        review_window_days=28,
        decision_rule="IF baseline low THEN targeted.",
        caveats=["Human review is required before any decision."],
        citations=[citation],
    )
    analysis = DataAnalystOutput(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        analysis=AnalysisSummary(
            detected_need="n", evidence_bullets=[], missing_data_flags=[], analysis_confidence=0.5
        ),
    )

    client = FakeChatClientFactory()
    _seed(client)
    runtime, _ = make_fake_runtime(client)
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=(),
                allowed_strategy_ids=(),
                allowed_citation_ids=("GROUP-DEMO-el-01",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "FORBIDDEN_DETERMINATION" in report.issue_codes


async def test_validator_safe_summary_never_contains_raw_critique() -> None:
    from app.agents.shared.contracts import (
        AnalysisSummary,
        Citation,
        CitationSourceType,
        DataAnalystOutput,
        SupportRecommendationDraft,
    )

    # Register a validator LLM critique with adversarial free text.
    client = FakeChatClientFactory()
    client.register_response(
        "validator-agent",
        {
            "warning_codes": ["real free-text leak here"],
            "repair_guidance": "the user's raw concern text is ...",
        },
    )
    runtime, _ = make_fake_runtime(client)

    citation = Citation(
        citation_id="GROUP-DEMO-el-01",
        dealer_group_id=DEFAULT_DEALER_GROUP,
        source_type=CitationSourceType.SYNTHETIC_FIXTURE,
        source_title="Fixture",
        section_or_page="",
        evidence_summary="synthetic",
        source_ref="fixture://demo/el-01",
        retrieved_at="2026-01-05T09:00:00Z",
        confidence=0.7,
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
        citations=[citation],
    )
    analysis = DataAnalystOutput(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        analysis=AnalysisSummary(
            detected_need="n", evidence_bullets=[], missing_data_flags=[], analysis_confidence=0.5
        ),
    )
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=(),
                allowed_strategy_ids=(),
                allowed_citation_ids=("GROUP-DEMO-el-01",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=True,
    )
    # `safe_summary` and `warning_codes` must not carry the raw free-text.
    assert "raw concern" not in report.safe_summary.lower()
    # The leaky code was lowercase with spaces, so `enforce_code` drops it.
    # Assert that rather than looping over what is now an empty list.
    assert report.warning_codes == []
    assert "the user's raw concern text" not in report.repair_guidance.lower()
    _ = _bundle_from_ctx  # silence unused
