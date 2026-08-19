from __future__ import annotations

from typing import Any

from app.agents.data_analyst import DataAnalystAgent
from app.agents.support_recommender import SupportRecommendationAgent
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput

from .conftest import (
    DEFAULT_DISTRICT,
    canned_data_analyst_output,
    canned_recommendation_draft,
)
from .fakes import FakeFoundryClient, build_bindings, make_fake_adapter
from .test_agents import _analyst_ctx, _bundle, _rec_ctx


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
    adapter = _adapter_with_adversarial_critique(
        {
            "warning_codes": [
                "leaked user secret abcdef",
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
    draft = SupportRecommendationAgent(adapter).recommend(analysis, _rec_ctx())
    bundle = _bundle()
    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id=DEFAULT_DISTRICT,
                allowed_resource_ids=(),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                allowed_citation_ids=tuple(c.citation_id for c in bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=True,
    )
    assert set(report.warning_codes) == {"REAL_WARNING_CODE", "TRIMMED_CODE"}
    for w in report.warning_codes:
        assert "password" not in w.lower()
        assert "concern" not in w.lower()
