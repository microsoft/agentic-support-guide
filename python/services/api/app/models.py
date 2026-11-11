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
    # How the API authenticates OUTBOUND to Foundry. Deliberately not named
    # `auth_mode`: this endpoint is anonymous, and a bare "entra" here reads as
    # "the API requires a sign-in", which it does not. Inbound protection is
    # `api_auth_mode` on /health/details.
    foundry_auth_mode: str
    # Proves which build is serving. A deploy can succeed and still leave the
    # previous code running, which no other field here would reveal.
    build_id: str


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
    # Which retriever is actually serving evidence. Without this, a Module 6
    # misconfiguration looks identical to a working one from the outside.
    evidence_source: str
    evidence_knowledge_base: str
    # False for a remote knowledge base: readiness is a configuration check and
    # cannot prove a remote source holds anything without a network call.
    evidence_verified: bool
    # `shared_key`, `unprotected` or `misconfigured`. Surfaced so an
    # unauthenticated deployment is visible from outside rather than only in
    # app settings.
    api_auth_mode: str
    dealer_group_isolation_enabled: bool
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


class AreaSlice(BaseModel):
    process_area: str
    value: float


class DashboardSummary(BaseModel):
    kpi_cards: list[KpiCard]
    process_score_trend: list[TrendPoint]
    area_distribution: list[AreaSlice]
    engagement_trend: list[TrendPoint]
    notes: list[str]


class DealershipSummary(BaseModel):
    dealership_id: str
    display_label: str
    region_id: str
    segment: str
    process_score: float
    appointment_attendance_rate: float
    followup_index: float
    engagement_index: float
    flagged: bool


class DealershipsResponse(BaseModel):
    dealerships: list[DealershipSummary]
    total: int


class BandBucket(BaseModel):
    label: str
    count: int
    percent: float


class AreaTrend(BaseModel):
    process_area: str
    points: list[TrendPoint]


class ScoresSummary(BaseModel):
    filters_applied: dict[str, str | None]
    total_records: int
    band_distribution: list[BandBucket]
    area_trends: list[AreaTrend]
    recommendation_bullets: list[str]
    performance_summary: str
    generated_by: str
    table_rows: list[dict[str, str | int | float]]


class OperationsSummary(BaseModel):
    attendance_trend: list[TrendPoint]
    escalation_trend: list[TrendPoint]
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


class GoalOption(BaseModel):
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
    dealerships: list[Option]
    categories: list[CategoryOption]
    goals: list[GoalOption]
    strategies: list[StrategyOption]
    # The UI has no identity to derive a dealer group from, so the roster comes
    # from here rather than being hardcoded in the bundle.
    dealer_groups: list[str] = []


class SupportPlanRequest(BaseModel):
    dealership_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    category: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    concern_text: str = Field(min_length=1, max_length=1000)
    dealer_group_id: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9\-]{1,31}$")


class RecommendationResource(BaseModel):
    id: str
    label: str
    kind: str


class RecommendationCitation(BaseModel):
    """Dealer-group-scoped evidence pointer surfaced to the UI."""

    citation_id: str
    dealer_group_id: str
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

    dealer_group_id: str = Field(min_length=2, max_length=32)
    detected_need: str = Field(max_length=300)
    evidence_summary: list[str] = Field(max_length=20)
    rationale: str = Field(max_length=2000)
    support_tier: str = Field(max_length=60)
    recommended_frequency: str = Field(max_length=120)
    grouping_guidance: str = Field(max_length=200)
    resource_matches: list[RecommendationResource] = Field(max_length=20)
    manager_next_steps: list[str] = Field(max_length=20)
    progress_monitoring: list[str] = Field(max_length=20)
    review_window_days: int = Field(ge=0, le=365)
    decision_rule: str = Field(max_length=300)
    caveats: list[str] = Field(max_length=20)
    goal_suggestions: list[str] = Field(max_length=20)
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
    dealer_group_id: str
    # What the application controls did on this run. `None` means not
    # measured -- the UI must render absence, not zero.
    evidence_count: int | None = None
    citation_count: int | None = None
    citations_proposed: int | None = None
    citations_accepted: int | None = None
    resources_proposed: int | None = None
    resources_accepted: int | None = None
    unknown_resource_ids: list[str] = Field(default_factory=list)
    validator_status: str | None = None
    validation_reached: bool = False
    attempts: int | None = None
    deterministic_checks_total: int | None = None


class SavedPlan(BaseModel):
    plan_id: str
    dealership_id: str
    dealer_group_id: str
    category: str
    concern_text: str
    selected_goal: str | None
    selected_strategies: list[str]
    created_at: str
    recommendation: Recommendation
    human_review_state: str = "draft"


class SavedPlansResponse(BaseModel):
    plans: list[SavedPlan]
    total: int


class SavePlanRequest(BaseModel):
    dealership_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    category: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
    concern_text: str = Field(min_length=1, max_length=1000)
    selected_goal: str | None = Field(default=None, max_length=64)
    selected_strategies: list[str] = Field(default_factory=list, max_length=20)
    recommendation: Recommendation
    dealer_group_id: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9\-]{1,31}$")

    @model_validator(mode="after")
    def _dealer_group_must_match_recommendation(self) -> SavePlanRequest:
        """Refuse to persist a plan whose recommendation belongs elsewhere.

        The save endpoint does not re-run the pipeline, so this is the only
        place the tenant boundary is re-checked on the way in.
        """

        if self.recommendation.dealer_group_id != self.dealer_group_id:
            raise ValueError("recommendation.dealer_group_id must match dealer_group_id")
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
    dealer_group_id: str = ""
    evidence_count: int = 0
    citation_count: int = 0
    validator_status: str = ""


class AuditResponse(BaseModel):
    events: list[AuditEvent]
    total: int
    disclaimer: str
