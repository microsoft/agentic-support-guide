from __future__ import annotations

import json
from typing import Any

from app.agents.data_analyst import DataAnalystAgent, DataAnalystContext
from app.agents.shared.contracts import ResourceRef
from app.agents.support_recommender import (
    SupportRecommendationAgent,
    SupportRecommenderContext,
)
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput

from .conftest import (
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
)
from .fakes import FakeFoundryClient, build_bindings, make_fake_adapter


def _seed_client(
    *,
    resource_ids: list[str] | None = None,
    smart_goal_ids: list[str] | None = None,
    strategy_ids: list[str] | None = None,
    tier: str = "Targeted support (Tier 2)",
    caveats: list[str] | None = None,
) -> tuple[FakeFoundryClient, dict[str, Any]]:
    client = FakeFoundryClient()
    bindings = build_bindings()
    client.register_response(
        bindings["data-analyst-agent"].assistant_id,
        canned_data_analyst_output(),
    )
    client.register_response(
        bindings["support-recommendation-agent"].assistant_id,
        canned_recommendation_draft(
            resource_ids=resource_ids,
            smart_goal_ids=smart_goal_ids or ["SG-early-literacy-1"],
            strategy_ids=strategy_ids or ["ST-early-literacy-1"],
            tier=tier,
            caveats=caveats,
        ),
    )
    client.register_response(
        bindings["validator-agent"].assistant_id,
        canned_validator_critique(),
    )
    return client, bindings


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
    client, _ = _seed_client()
    adapter = make_fake_adapter(client)
    result = DataAnalystAgent(adapter).analyze(_context())
    assert result.contract_version == "1.0.0"
    assert result.analysis.detected_need
    assert 0 <= result.analysis.analysis_confidence <= 1


def test_support_recommender_agent_returns_typed_draft() -> None:
    client, _ = _seed_client()
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_context())
    ctx = SupportRecommenderContext(
        category="early-literacy",
        sanitized_concern_text="synthetic concern",
        allowed_resources=(),
        allowed_smart_goal_ids=("SG-early-literacy-1",),
        allowed_strategy_ids=("ST-early-literacy-1",),
    )
    draft = SupportRecommendationAgent(adapter).recommend(analysis, ctx)
    assert draft.contract_version == "1.0.0"
    assert draft.review_window_days > 0
    assert draft.rationale


def test_validator_agent_pass() -> None:
    client, _ = _seed_client()
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_context())
    draft = SupportRecommendationAgent(adapter).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
    )
    report = ValidatorAgent(adapter).validate(
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
    )
    assert report.passed, report.issue_codes


def test_validator_agent_flags_unknown_resource() -> None:
    client, _ = _seed_client(
        resource_ids=["RES-000-INVENTED"],
    )
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_context())
    draft = SupportRecommendationAgent(adapter).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(ResourceRef(id="RES-001", label="Kit", kind="guide"),),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
    )
    report = ValidatorAgent(adapter).validate(
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
    )
    assert not report.passed
    assert "UNKNOWN_RESOURCE_ID" in report.issue_codes


def test_validator_agent_flags_missing_caveats() -> None:
    client, _ = _seed_client(caveats=[])
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_context())
    draft = SupportRecommendationAgent(adapter).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
    )
    report = ValidatorAgent(adapter).validate(
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
    )
    assert not report.passed
    assert "MISSING_CAVEATS" in report.issue_codes


def test_validator_agent_flags_invalid_tier() -> None:
    client, _ = _seed_client(tier="Mystery Tier")
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_context())
    draft = SupportRecommendationAgent(adapter).recommend(
        analysis,
        SupportRecommenderContext(
            category="early-literacy",
            sanitized_concern_text="synthetic",
            allowed_resources=(),
            allowed_smart_goal_ids=("SG-early-literacy-1",),
            allowed_strategy_ids=("ST-early-literacy-1",),
        ),
    )
    report = ValidatorAgent(adapter).validate(
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
    )
    assert "INVALID_SUPPORT_TIER" in report.issue_codes


_ = json  # silence unused-import noise
