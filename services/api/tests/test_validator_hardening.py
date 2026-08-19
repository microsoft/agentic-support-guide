from __future__ import annotations

from typing import Any

from app.agents.data_analyst import DataAnalystAgent, DataAnalystContext
from app.agents.support_recommender import (
    SupportRecommendationAgent,
    SupportRecommenderContext,
)
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput

from .conftest import canned_data_analyst_output, canned_recommendation_draft
from .fakes import FakeFoundryClient, build_bindings, make_fake_adapter


def _analyst_ctx() -> DataAnalystContext:
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
        sanitized_concern_text="synthetic concern text",
    )


def _adapter_with_adversarial_critique(critique: dict[str, Any]) -> Any:
    client = FakeFoundryClient()
    bindings = build_bindings()
    client.register_response(
        bindings["data-analyst-agent"].assistant_id,
        canned_data_analyst_output(),
    )
    client.register_response(
        bindings["support-recommendation-agent"].assistant_id,
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    client.register_response(
        bindings["validator-agent"].assistant_id,
        critique,
    )
    return make_fake_adapter(client)


def test_validator_drops_non_conforming_llm_warnings() -> None:
    """Warning codes not matching UPPER_SNAKE format must be discarded."""

    adapter = _adapter_with_adversarial_critique(
        {
            "warning_codes": [
                "leaked user secret abcdef",  # freeform text
                "here is the concern: password=hunter2",
                "OK",
                "REAL_WARNING_CODE",
                "lower_case_should_drop",
                "  TRIMMED_CODE  ",
            ],
            "repair_guidance": "",
        }
    )
    analysis = DataAnalystAgent(adapter).analyze(_analyst_ctx())
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
    # Only the properly-shaped codes survive; freeform text is discarded.
    assert set(report.warning_codes) == {"REAL_WARNING_CODE", "TRIMMED_CODE"}
    for w in report.warning_codes:
        assert "password" not in w.lower()
        assert "concern" not in w.lower()
