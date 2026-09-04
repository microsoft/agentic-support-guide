"""Pydantic v2 models used at the HTTP boundary.

These are the source of truth for the FastAPI OpenAPI contract. Frontend
clients should generate or hand-write TypeScript types that mirror these
shapes. Raw model files are not shared across languages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    banner: str
    provider_configured: bool
    auth_mode: str


class HealthCheckItem(BaseModel):
    name: str
    label: str
    ok: bool
    detail: str


class HealthDetailsResponse(BaseModel):
    status: str
    service: str
    version: str
    active_provider: str
    foundry_project_configured: bool
    agent_definitions_valid: bool
    model_deployments_configured: bool
    service_side_remote_workflow_active: bool
    evidence_fixture_available: bool
    district_isolation_enabled: bool
    customer_demo_ready: bool
    checks: list[HealthCheckItem]
    warnings: list[str] = Field(default_factory=list)
    guidance: str


class DemoResetResponse(BaseModel):
    status: str
    plans_reset: int
    audit_reset: int


class AgentTraceStep(BaseModel):
    agent: str
    status: str
    provider: str
    model: str
    latency_ms: int
    token_estimate: int | None
    issue_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    citation_count: int = 0


class KpiCard(BaseModel):
    id: str
    label: str
    value: float
    unit: str
    delta: float
    trend: str


class TrendPoint(BaseModel):
    period: str
    value: float


class DomainSlice(BaseModel):
    domain: str
    value: float


class DashboardSummary(BaseModel):
    kpi_cards: list[KpiCard]
    proficiency_trend: list[TrendPoint]
    domain_distribution: list[DomainSlice]
    engagement_trend: list[TrendPoint]
    notes: list[str]


class LearnerSummary(BaseModel):
    learner_id: str
    display_label: str
    school_id: str
    grade: int
    group: str
    proficiency_index: float
    attendance_rate: float
    behavior_index: float
    engagement_index: float
    flagged: bool


class LearnersResponse(BaseModel):
    learners: list[LearnerSummary]
    total: int


class ProficiencyBucket(BaseModel):
    label: str
    count: int
    percent: float


class DomainTrend(BaseModel):
    domain: str
    points: list[TrendPoint]


class AssessmentsSummary(BaseModel):
    filters_applied: dict[str, str | None]
    total_records: int
    proficiency_distribution: list[ProficiencyBucket]
    domain_trends: list[DomainTrend]
    recommendation_bullets: list[str]
    performance_summary: str
    generated_by: str
    table_rows: list[dict[str, str | int | float]]


class BehaviorSummary(BaseModel):
    attendance_trend: list[TrendPoint]
    behavior_trend: list[TrendPoint]
    engagement_trend: list[TrendPoint]
    highlights: list[str]
    total_records: int


class Option(BaseModel):
    id: str
    label: str


class CategoryOption(BaseModel):
    id: str
    label: str
    description: str


class SmartGoalOption(BaseModel):
    id: str
    label: str
    category_id: str
    description: str


class StrategyOption(BaseModel):
    id: str
    label: str
    category_id: str
    description: str


class SupportOptions(BaseModel):
    learners: list[Option]
    categories: list[CategoryOption]
    smart_goals: list[SmartGoalOption]
    strategies: list[StrategyOption]


class SupportPlanRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    category: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    concern_text: str = Field(min_length=1, max_length=1000)
    district_id: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9\-]{1,31}$")


class RecommendationResource(BaseModel):
    id: str
    label: str
    kind: str


class RecommendationCitation(BaseModel):
    """District-scoped evidence pointer surfaced to the UI."""

    citation_id: str
    district_id: str
    source_type: str
    source_title: str
    section_or_page: str = ""
    evidence_summary: str
    source_ref: str
    retrieved_at: str
    confidence: float


class Recommendation(BaseModel):
    """Coordinator output, also accepted back on POST /api/supports/plans.

    The bounds below are not a substitute for the validator - they cap what a
    client can persist through the save endpoint, which does not re-run the
    three-agent pipeline.
    """

    district_id: str = Field(min_length=2, max_length=32)
    detected_need: str = Field(max_length=300)
    evidence_summary: list[str] = Field(max_length=20)
    rationale: str = Field(max_length=2000)
    support_tier: str = Field(max_length=60)
    recommended_frequency: str = Field(max_length=120)
    grouping_guidance: str = Field(max_length=200)
    resource_matches: list[RecommendationResource] = Field(max_length=20)
    educator_next_steps: list[str] = Field(max_length=20)
    progress_monitoring: list[str] = Field(max_length=20)
    review_window_days: int = Field(ge=0, le=365)
    decision_rule: str = Field(max_length=300)
    caveats: list[str] = Field(max_length=20)
    smart_goal_suggestions: list[str] = Field(max_length=20)
    strategy_suggestions: list[str] = Field(max_length=20)
    citations: list[RecommendationCitation] = Field(max_length=20)
    completeness: dict[str, bool | list[str]]
    human_review_state: str = Field(max_length=40)
    generated_by: str = Field(max_length=300)


class RecommendationEnvelope(BaseModel):
    """Response for POST /api/recommendations/support-plan.

    `status` reflects the coordinator outcome. When status != 'ok' the
    recommendation body is omitted and the UI must render a safe state.
    """

    status: str
    error_code: str | None = None
    error_message: str | None = None
    recommendation: Recommendation | None = None
    agent_trace: list[AgentTraceStep] = Field(default_factory=list)
    provider_model: str
    correlation_id: str
    district_id: str


class SavedPlan(BaseModel):
    plan_id: str
    learner_id: str
    district_id: str
    category: str
    concern_text: str
    selected_smart_goal: str | None
    selected_strategies: list[str]
    created_at: str
    recommendation: Recommendation
    human_review_state: str = "draft"


class SavedPlansResponse(BaseModel):
    plans: list[SavedPlan]
    total: int


class SavePlanRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    category: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    concern_text: str = Field(min_length=1, max_length=1000)
    selected_smart_goal: str | None = Field(default=None, max_length=64)
    selected_strategies: list[str] = Field(default_factory=list, max_length=20)
    recommendation: Recommendation
    district_id: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9\-]{1,31}$")

    @model_validator(mode="after")
    def _district_must_match_recommendation(self) -> SavePlanRequest:
        """Refuse to persist a plan whose recommendation belongs elsewhere.

        The save endpoint does not re-run the pipeline, so this is the only
        place the district boundary is re-checked on the way in.
        """

        if self.recommendation.district_id != self.district_id:
            raise ValueError("recommendation.district_id must match district_id")
        return self


class ReviewTransitionRequest(BaseModel):
    """Request body for POST /api/supports/plans/{plan_id}/review."""

    to_state: str = Field(pattern=r"^(pending_review|approved|rejected)$")
    user_label: str = Field(default="Staff S-01", max_length=32)


class AuditEvent(BaseModel):
    event_id: str
    timestamp: str
    endpoint: str
    context: str
    user: str
    provider_model: str
    duration_ms: int
    token_estimate: int
    status: str
    correlation_id: str = ""
    district_id: str = ""
    evidence_count: int = 0
    citation_count: int = 0
    validator_status: str = ""


class AuditResponse(BaseModel):
    events: list[AuditEvent]
    total: int
    disclaimer: str
