from __future__ import annotations

from app.agents.data_analyst import DataAnalystAgent, DataAnalystContext
from app.agents.shared.contracts import ResourceRef
from app.agents.support_recommender import (
    SupportRecommendationAgent,
    SupportRecommenderContext,
)
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from app.llm import MockLlmProvider

from .conftest import (
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
)


def _mock() -> MockLlmProvider:
    provider = MockLlmProvider()
    provider.register("data_analyst_output", canned_data_analyst_output())
    provider.register(
        "support_recommendation_draft",
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    provider.register("validator_llm_critique", canned_validator_critique())
    return provider


def _context() -> DataAnalystContext:
    return DataAnalystContext(
        learner_label="Learner 0001",
        grade=3,
        school_id="SCH-001",
        group="GRP-A",
        proficiency_index=45.0,
        attendance_rate=0.9,
        behavior_index=70.0,
        engagement_index=65.0,
        assessment_count=4,
        behavior_record_count=2,
        category="early-literacy",
        sanitized_concern_text="Letter-sound fluency below expected pace.",
    )


def test_data_analyst_agent_returns_typed_output() -> None:
    provider = _mock()
    agent = DataAnalystAgent(provider)
    result = agent.analyze(_context(), max_tokens=400, timeout_seconds=10)
    assert result.contract_version == "1.0.0"
    assert result.analysis.detected_need
    assert 0 <= result.analysis.analysis_confidence <= 1


def test_support_recommender_agent_returns_typed_draft() -> None:
    provider = _mock()
    analysis = DataAnalystAgent(provider).analyze(_context(), max_tokens=400, timeout_seconds=10)
    agent = SupportRecommendationAgent(provider)
    ctx = SupportRecommenderContext(
        category="early-literacy",
        sanitized_concern_text="synthetic concern",
        allowed_resources=(),
        allowed_smart_goal_ids=("SG-early-literacy-1",),
        allowed_strategy_ids=("ST-early-literacy-1",),
    )
    draft = agent.recommend(analysis, ctx, max_tokens=400, timeout_seconds=10)
    assert draft.contract_version == "1.0.0"
    assert draft.review_window_days > 0
    assert draft.rationale


def test_validator_agent_pass() -> None:
    provider = _mock()
    analysis = DataAnalystAgent(provider).analyze(_context(), max_tokens=400, timeout_seconds=10)
    draft = SupportRecommendationAgent(provider).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
        max_tokens=400,
        timeout_seconds=10,
    )
    report = ValidatorAgent(provider).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                allowed_resource_ids=(),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=True,
        max_tokens=200,
        timeout_seconds=10,
    )
    assert report.passed, report.issue_codes


def test_validator_agent_flags_unknown_resource() -> None:
    provider = _mock()
    provider.register(
        "support_recommendation_draft",
        canned_recommendation_draft(
            resource_ids=["RES-000-INVENTED"],
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    analysis = DataAnalystAgent(provider).analyze(_context(), max_tokens=400, timeout_seconds=10)
    draft = SupportRecommendationAgent(provider).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(ResourceRef(id="RES-001", label="Kit", kind="guide"),),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
        max_tokens=400,
        timeout_seconds=10,
    )
    report = ValidatorAgent(provider).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                allowed_resource_ids=("RES-001",),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
        max_tokens=200,
        timeout_seconds=10,
    )
    assert not report.passed
    assert "UNKNOWN_RESOURCE_ID" in report.issue_codes


def test_validator_agent_flags_missing_caveats() -> None:
    provider = _mock()
    provider.register(
        "support_recommendation_draft",
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
            caveats=[],
        ),
    )
    analysis = DataAnalystAgent(provider).analyze(_context(), max_tokens=400, timeout_seconds=10)
    draft = SupportRecommendationAgent(provider).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
        max_tokens=400,
        timeout_seconds=10,
    )
    report = ValidatorAgent(provider).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                allowed_resource_ids=(),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
        max_tokens=200,
        timeout_seconds=10,
    )
    assert not report.passed
    assert "MISSING_CAVEATS" in report.issue_codes


def test_validator_agent_flags_invalid_tier() -> None:
    provider = _mock()
    provider.register(
        "support_recommendation_draft",
        canned_recommendation_draft(
            tier="Mystery Tier",
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    analysis = DataAnalystAgent(provider).analyze(_context(), max_tokens=400, timeout_seconds=10)
    draft = SupportRecommendationAgent(provider).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
        max_tokens=400,
        timeout_seconds=10,
    )
    report = ValidatorAgent(provider).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                allowed_resource_ids=(),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
        max_tokens=200,
        timeout_seconds=10,
    )
    assert "INVALID_SUPPORT_TIER" in report.issue_codes
