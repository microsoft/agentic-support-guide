from __future__ import annotations

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
    DEFAULT_DISTRICT,
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
    cited_ids: list[str] | None = None,
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
            cited_ids=cited_ids,
        ),
    )
    client.register_response(
        bindings["validator-agent"].assistant_id,
        canned_validator_critique(),
    )
    return client, bindings


def _analyst_ctx() -> DataAnalystContext:
    return DataAnalystContext(
        district_id=DEFAULT_DISTRICT,
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


def _bundle() -> EvidenceBundle:
    retriever = FixtureEvidenceRetriever()
    return retriever.retrieve(
        EvidenceRequest(
            district_id=DEFAULT_DISTRICT,
            category="early-literacy",
            detected_need_hint="",
        )
    )


def _rec_ctx() -> SupportRecommenderContext:
    return SupportRecommenderContext(
        district_id=DEFAULT_DISTRICT,
        category="early-literacy",
        sanitized_concern_text="synthetic",
        allowed_resources=(),
        allowed_smart_goal_ids=("SG-early-literacy-1",),
        allowed_strategy_ids=("ST-early-literacy-1",),
        evidence=_bundle(),
    )


def test_data_analyst_agent_returns_typed_output() -> None:
    client, _ = _seed_client()
    adapter = make_fake_adapter(client)
    result = DataAnalystAgent(adapter).analyze(_analyst_ctx())
    assert result.contract_version == "1.0.0"
    assert result.district_id == DEFAULT_DISTRICT
    assert result.analysis.detected_need


def test_support_recommender_attaches_district_citations() -> None:
    client, _ = _seed_client()
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_analyst_ctx())
    draft = SupportRecommendationAgent(adapter).recommend(analysis, _rec_ctx())
    assert draft.district_id == DEFAULT_DISTRICT
    assert len(draft.citations) >= 1
    for c in draft.citations:
        assert c.district_id == DEFAULT_DISTRICT


def test_support_recommender_respects_cited_ids_selection() -> None:
    bundle = _bundle()
    first_id = bundle.citations[0].citation_id
    client, _ = _seed_client(cited_ids=[first_id])
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_analyst_ctx())
    draft = SupportRecommendationAgent(adapter).recommend(analysis, _rec_ctx())
    assert [c.citation_id for c in draft.citations] == [first_id]


def test_validator_pass_with_valid_citations() -> None:
    client, _ = _seed_client()
    adapter = make_fake_adapter(client)
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
    assert report.passed, report.issue_codes
    assert report.district_id == DEFAULT_DISTRICT
    assert report.safe_summary
    assert not report.failed_fields


def test_validator_flags_unknown_resource() -> None:
    client, _ = _seed_client(resource_ids=["RES-000-INVENTED"])
    adapter = make_fake_adapter(client)
    analysis = DataAnalystAgent(adapter).analyze(_analyst_ctx())
    ctx = SupportRecommenderContext(
        district_id=DEFAULT_DISTRICT,
        category="early-literacy",
        sanitized_concern_text="synthetic",
        allowed_resources=(ResourceRef(id="RES-001", label="Kit", kind="guide"),),
        allowed_smart_goal_ids=("SG-early-literacy-1",),
        allowed_strategy_ids=("ST-early-literacy-1",),
        evidence=_bundle(),
    )
    draft = SupportRecommendationAgent(adapter).recommend(analysis, ctx)
    bundle = _bundle()
    report = ValidatorAgent(adapter).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                district_id=DEFAULT_DISTRICT,
                allowed_resource_ids=("RES-001",),
                allowed_smart_goal_ids=("SG-early-literacy-1",),
                allowed_strategy_ids=("ST-early-literacy-1",),
                allowed_citation_ids=tuple(c.citation_id for c in bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=False,
    )
    assert not report.passed
    assert "UNKNOWN_RESOURCE_ID" in report.issue_codes
    assert "resource_ids" in report.failed_fields


def test_validator_flags_missing_caveats() -> None:
    client, _ = _seed_client(caveats=[])
    adapter = make_fake_adapter(client)
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
        use_llm_critique=False,
    )
    assert not report.passed
    assert "MISSING_CAVEATS" in report.issue_codes
