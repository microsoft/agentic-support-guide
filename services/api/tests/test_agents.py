from __future__ import annotations

import json
import re
from typing import Any

from app.agents.data_analyst import DataAnalystAgent, DataAnalystContext
from app.agents.shared.contracts import ResourceRef
from app.agents.support_recommender import (
    SupportRecommendationAgent,
    SupportRecommenderContext,
)
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from app.evidence import EvidenceBundle, EvidenceRequest, FixtureEvidenceRetriever

from .conftest import (
    DEFAULT_DEALER_GROUP,
    canned_data_analyst_output,
    canned_recommendation_draft,
    canned_validator_critique,
    sample_area_series,
    sample_operations_series,
)
from .fakes import FakeChatClientFactory, make_fake_runtime


def _seed_client(
    *,
    resource_ids: list[str] | None = None,
    goal_ids: list[str] | None = None,
    strategy_ids: list[str] | None = None,
    tier: str = "Focused",
    caveats: list[str] | None = None,
    cited_ids: list[str] | None = None,
) -> tuple[FakeChatClientFactory, dict[str, Any]]:
    client = FakeChatClientFactory()
    client.register_response(
        "data-analyst-agent",
        canned_data_analyst_output(),
    )
    client.register_response(
        "support-recommendation-agent",
        canned_recommendation_draft(
            resource_ids=resource_ids,
            goal_ids=goal_ids or ["GOAL-lead-response-1"],
            strategy_ids=strategy_ids or ["ST-lead-response-1"],
            tier=tier,
            caveats=caveats,
            cited_ids=cited_ids,
        ),
    )
    client.register_response(
        "validator-agent",
        canned_validator_critique(),
    )
    return client, {}


def _analyst_ctx() -> DataAnalystContext:
    return DataAnalystContext(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        dealership_label="Dealership 0001",
        segment="SEG-VOLUME",
        region_id="REG-001",
        process_score=45.0,
        appointment_attendance_rate=0.9,
        followup_index=70.0,
        engagement_index=65.0,
        area_series=sample_area_series(),
        operations_series=sample_operations_series(),
        category="lead-response",
        concern_text="First response to online enquiries is slower than the standard.",
    )


async def _bundle() -> EvidenceBundle:
    retriever = FixtureEvidenceRetriever()
    return await retriever.retrieve(
        EvidenceRequest(
            dealer_group_id=DEFAULT_DEALER_GROUP,
            category="lead-response",
            detected_need_hint="",
        )
    )


async def _rec_ctx() -> SupportRecommenderContext:
    return SupportRecommenderContext(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        category="lead-response",
        concern_text="synthetic",
        allowed_resources=(),
        allowed_goal_ids=("GOAL-lead-response-1",),
        allowed_strategy_ids=("ST-lead-response-1",),
        evidence=await _bundle(),
    )


async def test_data_analyst_agent_returns_typed_output() -> None:
    client, _ = _seed_client()
    runtime, _ = make_fake_runtime(client)
    result = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    assert result.contract_version == "1.0.0"
    assert result.dealer_group_id == DEFAULT_DEALER_GROUP
    assert result.analysis.detected_need


async def test_analyst_prompt_carries_the_score_and_operations_series() -> None:
    """The agent is asked for cross-area and temporal analysis, so it has to
    receive both series. It previously got only a record count, and every test
    still passed because none of them inspected the outbound prompt.
    """

    client, _ = _seed_client()
    runtime, _ = make_fake_runtime(client)
    await DataAnalystAgent(runtime).analyze(_analyst_ctx())

    prompt = next(c["user_message"] for c in client.calls() if c["role"] == "data-analyst-agent")
    match = re.search(r"kind=synthetic_facts\n(.*?)\n<<<END", prompt, re.S)
    assert match, "the analyst prompt carries no synthetic_facts block"
    facts = json.loads(match.group(1))

    series = _analyst_ctx().area_series
    assert facts["score_periods"] == list(series.periods)
    assert facts["score_by_process_area"]["lead-response"] == list(
        series.scores_by_area["lead-response"]
    )
    assert facts["latest_band_by_process_area"]["lead-response"] == "Developing"

    ops = _analyst_ctx().operations_series
    assert facts["appointment_attendance_rate_by_period"] == list(ops.appointment_attendance_rate)
    assert facts["escalations_by_period"] == list(ops.escalations)
    assert facts["followup_completion_by_period"] == list(ops.followup_completion)


async def test_analyst_prompt_reaches_the_model_as_valid_json() -> None:
    """The facts block is sanitised on the way out; it must still parse."""

    client, _ = _seed_client()
    runtime, _ = make_fake_runtime(client)
    await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    prompt = next(c["user_message"] for c in client.calls() if c["role"] == "data-analyst-agent")
    match = re.search(r"kind=synthetic_facts\n(.*?)\n<<<END", prompt, re.S)
    assert match, "the analyst prompt carries no synthetic_facts block"
    assert isinstance(json.loads(match.group(1)), dict)


async def test_support_recommender_attaches_dealer_group_citations() -> None:
    client, _ = _seed_client()
    runtime, _ = make_fake_runtime(client)
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, await _rec_ctx())
    assert draft.dealer_group_id == DEFAULT_DEALER_GROUP
    assert len(draft.citations) >= 1
    for c in draft.citations:
        assert c.dealer_group_id == DEFAULT_DEALER_GROUP


async def test_support_recommender_respects_cited_ids_selection() -> None:
    bundle = await _bundle()
    first_id = bundle.citations[0].citation_id
    client, _ = _seed_client(cited_ids=[first_id])
    runtime, _ = make_fake_runtime(client)
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, await _rec_ctx())
    assert [c.citation_id for c in draft.citations] == [first_id]


async def test_validator_pass_with_valid_citations() -> None:
    client, _ = _seed_client()
    runtime, _ = make_fake_runtime(client)
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, await _rec_ctx())
    bundle = await _bundle()
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=("GOAL-lead-response-1",),
                allowed_strategy_ids=("ST-lead-response-1",),
                allowed_citation_ids=tuple(c.citation_id for c in bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=True,
    )
    assert report.passed, report.issue_codes
    assert report.dealer_group_id == DEFAULT_DEALER_GROUP
    assert report.safe_summary
    assert not report.failed_fields


async def test_validator_flags_unknown_resource() -> None:
    client, _ = _seed_client(resource_ids=["RES-000-INVENTED"])
    runtime, _ = make_fake_runtime(client)
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    ctx = SupportRecommenderContext(
        dealer_group_id=DEFAULT_DEALER_GROUP,
        category="lead-response",
        concern_text="synthetic",
        allowed_resources=(ResourceRef(id="RES-001", label="Kit", kind="guide"),),
        allowed_goal_ids=("GOAL-lead-response-1",),
        allowed_strategy_ids=("ST-lead-response-1",),
        evidence=await _bundle(),
    )
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, ctx)
    bundle = await _bundle()
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=("RES-001",),
                allowed_goal_ids=("GOAL-lead-response-1",),
                allowed_strategy_ids=("ST-lead-response-1",),
                allowed_citation_ids=tuple(c.citation_id for c in bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "UNKNOWN_RESOURCE_ID" in report.issue_codes
    assert "resource_ids" in report.failed_fields


async def test_validator_flags_missing_caveats() -> None:
    client, _ = _seed_client(caveats=[])
    runtime, _ = make_fake_runtime(client)
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, await _rec_ctx())
    bundle = await _bundle()
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=("GOAL-lead-response-1",),
                allowed_strategy_ids=("ST-lead-response-1",),
                allowed_citation_ids=tuple(c.citation_id for c in bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "MISSING_CAVEATS" in report.issue_codes
