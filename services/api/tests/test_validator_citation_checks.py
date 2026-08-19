from __future__ import annotations

from app.agents.data_analyst import DataAnalystAgent
from app.agents.support_recommender import SupportRecommendationAgent
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from app.evidence import EvidenceBundle

from .conftest import (
    DEFAULT_DISTRICT,
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
)
from .fakes import FakeFoundryClient, build_bindings, make_fake_adapter
from .test_agents import _analyst_ctx, _rec_ctx


def _seed(client: FakeFoundryClient, bindings: dict) -> None:  # type: ignore[type-arg]
    client.register_response(
        bindings["data-analyst-agent"].assistant_id, canned_data_analyst_output()
    )
    client.register_response(
        bindings["support-recommendation-agent"].assistant_id,
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"], strategy_ids=["ST-early-literacy-1"]
        ),
    )
    client.register_response(bindings["validator-agent"].assistant_id, canned_validator_critique())


def _bundle_from_ctx() -> EvidenceBundle:
    return _rec_ctx().evidence


def test_validator_fails_on_missing_citations() -> None:
    """Empty citations list on the draft must trigger MISSING_CITATIONS."""

    from app.agents.support_recommender.agent import SupportRecommenderContext
    from app.evidence import EvidenceBundle

    client = FakeFoundryClient()
    bindings = build_bindings()
    _seed(client, bindings)
    adapter = make_fake_adapter(client)

    empty_bundle = EvidenceBundle(district_id=DEFAULT_DISTRICT, citations=())
    ctx = SupportRecommenderContext(
        district_id=DEFAULT_DISTRICT,
        category="early-literacy",
        sanitized_concern_text="synthetic",
        allowed_resources=(),
        allowed_smart_goal_ids=("SG-early-literacy-1",),
        allowed_strategy_ids=("ST-early-literacy-1",),
        evidence=empty_bundle,
    )
    analysis = DataAnalystAgent(adapter).analyze(_analyst_ctx())
    draft = SupportRecommendationAgent(adapter).recommend(analysis, ctx)
    assert list(draft.citations) == []

    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id=DEFAULT_DISTRICT,
                allowed_resource_ids=(),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
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


def test_validator_flags_forbidden_determination_language() -> None:
    """Draft mentioning diagnosis must trigger FORBIDDEN_DETERMINATION."""

    from app.agents.shared.contracts import (
        AnalysisSummary,
        Citation,
        CitationSourceType,
        DataAnalystOutput,
        SupportRecommendationDraft,
    )

    citation = Citation(
        citation_id="DIST-DEMO-el-01",
        district_id=DEFAULT_DISTRICT,
        source_type=CitationSourceType.SYNTHETIC_FIXTURE,
        source_title="Fixture",
        section_or_page="",
        evidence_summary="synthetic",
        source_ref="fixture://demo/el-01",
        retrieved_at="2026-01-05T09:00:00Z",
        confidence=0.7,
    )
    draft = SupportRecommendationDraft(
        district_id=DEFAULT_DISTRICT,
        detected_need="synthetic",
        support_tier="Targeted support",
        recommended_frequency="3x weekly",
        grouping_guidance="small group",
        resource_ids=[],
        rationale="The synthetic learner appears to warrant a diagnosis of a reading disorder.",
        smart_goal_suggestions=[],
        strategy_suggestions=[],
        educator_next_steps=["Confirm baseline."],
        progress_monitoring=["Weekly probe."],
        review_window_days=28,
        decision_rule="IF baseline low THEN targeted.",
        caveats=["Human review is required before any decision."],
        citations=[citation],
    )
    analysis = DataAnalystOutput(
        district_id=DEFAULT_DISTRICT,
        analysis=AnalysisSummary(
            detected_need="n", evidence_bullets=[], missing_data_flags=[], analysis_confidence=0.5
        ),
    )

    client = FakeFoundryClient()
    bindings = build_bindings()
    _seed(client, bindings)
    adapter = make_fake_adapter(client)
    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id=DEFAULT_DISTRICT,
                allowed_resource_ids=(),
                allowed_smart_goal_ids=(),
                allowed_strategy_ids=(),
                allowed_citation_ids=("DIST-DEMO-el-01",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "FORBIDDEN_DETERMINATION" in report.issue_codes


def test_validator_safe_summary_never_contains_raw_critique() -> None:
    from app.agents.shared.contracts import (
        AnalysisSummary,
        Citation,
        CitationSourceType,
        DataAnalystOutput,
        SupportRecommendationDraft,
    )

    # Register a validator LLM critique with adversarial free text.
    client = FakeFoundryClient()
    bindings = build_bindings()
    client.register_response(
        bindings["validator-agent"].assistant_id,
        {
            "warning_codes": ["real free-text leak here"],
            "repair_guidance": "the user's raw concern text is ...",
        },
    )
    adapter = make_fake_adapter(client)

    citation = Citation(
        citation_id="DIST-DEMO-el-01",
        district_id=DEFAULT_DISTRICT,
        source_type=CitationSourceType.SYNTHETIC_FIXTURE,
        source_title="Fixture",
        section_or_page="",
        evidence_summary="synthetic",
        source_ref="fixture://demo/el-01",
        retrieved_at="2026-01-05T09:00:00Z",
        confidence=0.7,
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
        citations=[citation],
    )
    analysis = DataAnalystOutput(
        district_id=DEFAULT_DISTRICT,
        analysis=AnalysisSummary(
            detected_need="n", evidence_bullets=[], missing_data_flags=[], analysis_confidence=0.5
        ),
    )
    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id=DEFAULT_DISTRICT,
                allowed_resource_ids=(),
                allowed_smart_goal_ids=(),
                allowed_strategy_ids=(),
                allowed_citation_ids=("DIST-DEMO-el-01",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=True,
    )
    # `safe_summary` and `warning_codes` must not carry the raw free-text.
    assert "raw concern" not in report.safe_summary.lower()
    for w in report.warning_codes:
        assert "raw" not in w.lower()
    assert "the user's raw concern text" not in report.repair_guidance.lower()
    _ = _bundle_from_ctx  # silence unused
