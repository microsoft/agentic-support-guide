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
from .fakes import FakeChatClientFactory, make_fake_runtime
from .test_agents import _analyst_ctx, _bundle, _rec_ctx


def _runtime_with_adversarial_critique(critique: dict[str, Any]) -> Any:
    client = FakeChatClientFactory()
    client.register_response(
        "data-analyst-agent",
        canned_data_analyst_output(),
    )
    client.register_response(
        "support-recommendation-agent",
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    client.register_response(
        "validator-agent",
        critique,
    )
    return make_fake_runtime(client)[0]


async def test_validator_drops_non_conforming_llm_warnings() -> None:
    runtime = _runtime_with_adversarial_critique(
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
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, await _rec_ctx())
    bundle = await _bundle()
    report = await ValidatorAgent(runtime).validate(
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
