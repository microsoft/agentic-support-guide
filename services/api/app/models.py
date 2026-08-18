"""Pydantic v2 models used at the HTTP boundary.

These are the source of truth for the FastAPI OpenAPI contract. Frontend
clients should generate or hand-write TypeScript types that mirror these
shapes. Raw model files are not shared across languages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    learner_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    concern_text: str = Field(min_length=1, max_length=1000)


class RecommendationResource(BaseModel):
    id: str
    label: str
    kind: str


class Recommendation(BaseModel):
    detected_need: str
    evidence_summary: list[str]
    rationale: str
    support_tier: str
    recommended_frequency: str
    grouping_guidance: str
    resource_matches: list[RecommendationResource]
    educator_next_steps: list[str]
    progress_monitoring: list[str]
    review_window_days: int
    decision_rule: str
    caveats: list[str]
    smart_goal_suggestions: list[str]
    strategy_suggestions: list[str]
    completeness: dict[str, bool | list[str]]
    generated_by: str


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


class SavedPlan(BaseModel):
    plan_id: str
    learner_id: str
    category: str
    concern_text: str
    selected_smart_goal: str | None
    selected_strategies: list[str]
    created_at: str
    recommendation: Recommendation


class SavedPlansResponse(BaseModel):
    plans: list[SavedPlan]
    total: int


class SavePlanRequest(BaseModel):
    learner_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    concern_text: str = Field(min_length=1, max_length=1000)
    selected_smart_goal: str | None = None
    selected_strategies: list[str] = Field(default_factory=list)
    recommendation: Recommendation


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


class AuditResponse(BaseModel):
    events: list[AuditEvent]
    total: int
    disclaimer: str
