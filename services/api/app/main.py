"""FastAPI application entry point.

All routes are mounted under /api. OpenAPI is served at /api/openapi.json
and the interactive docs at /api/docs. There is no CORS middleware because
the frontend uses the Vite dev proxy.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from . import assessments as assessments_mod
from . import audit as audit_mod
from . import behavior as behavior_mod
from . import dashboard as dashboard_mod
from . import learners as learners_mod
from .agents.shared.contracts import ResourceRef
from .config import (
    BASE_TIMESTAMP,
    PROTOTYPE_BANNER,
    SERVICE_NAME,
    SERVICE_VERSION,
    AzureFoundrySettings,
    load_foundry_settings,
)
from .contracts_registry import ContractsRegistry, load_registry
from .diagnostics import build_health_details
from .llm import AzureFoundryLlmProvider, LlmCallResult, LlmError, LlmProvider
from .models import (
    AssessmentsSummary,
    AuditEvent,
    AuditResponse,
    BehaviorSummary,
    DashboardSummary,
    DemoResetResponse,
    HealthDetailsResponse,
    HealthResponse,
    LearnersResponse,
    RecommendationEnvelope,
    SavedPlan,
    SavedPlansResponse,
    SavePlanRequest,
    SupportOptions,
    SupportPlanRequest,
)
from .plans_store import SavedPlansStore
from .repositories import Repositories, build_repositories
from .runtime_audit import RuntimeAuditLog
from .supports import build_support_options
from .telemetry import TelemetryRecorder
from .workflows import AgentCoordinator
from .workflows.coordinator import CoordinatorRequest


def _next_iso(offset_seconds: int) -> str:
    base = datetime.strptime(BASE_TIMESTAMP, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (base + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _UnconfiguredProvider(LlmProvider):
    name = "unconfigured"
    model = "unconfigured"
    display_name = "unconfigured (Azure AI Foundry not set up)"

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        timeout_seconds: float,
        response_schema_name: str,
    ) -> LlmCallResult:
        raise LlmError(
            "provider_missing",
            "Azure AI Foundry environment variables are not configured. "
            "Populate services/api/.env from the Terraform outputs.",
        )


def _select_provider(settings: AzureFoundrySettings) -> LlmProvider:
    if not settings.configured:
        return _UnconfiguredProvider()
    assert settings.endpoint and settings.deployment and settings.api_version
    return AzureFoundryLlmProvider(
        endpoint=settings.endpoint,
        deployment=settings.deployment,
        api_version=settings.api_version,
    )


LEARNERS_RESPONSE_MODEL = "LearnersResponse"  # kept for schema reference in tests


def create_app(
    *,
    provider_factory: Callable[[AzureFoundrySettings], LlmProvider] | None = None,
) -> FastAPI:
    settings = load_foundry_settings()
    app = FastAPI(
        title="Agentic Support Guide API",
        description=(
            "Prototype API demonstrating three collaborating agents backed "
            "by Azure AI Foundry. Synthetic data only."
        ),
        version=SERVICE_VERSION,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    repos: Repositories = build_repositories()
    plans_store = SavedPlansStore()
    plans_store.seed(
        specs=repos.seeded_plans,
        learners=repos.learners,
        assessments=repos.assessments,
        behavior=repos.behavior,
        resources=repos.resources,
    )
    telemetry = TelemetryRecorder(settings.application_insights_connection_string)
    runtime_audit = RuntimeAuditLog()
    provider = (provider_factory or _select_provider)(settings)
    contracts = load_registry()

    app.state.settings = settings
    app.state.repos = repos
    app.state.plans_store = plans_store
    app.state.telemetry = telemetry
    app.state.runtime_audit = runtime_audit
    app.state.provider = provider
    app.state.contracts = contracts

    def get_provider(request: Request) -> LlmProvider:
        return request.app.state.provider  # type: ignore[no-any-return]

    def get_settings_dep(request: Request) -> AzureFoundrySettings:
        return request.app.state.settings  # type: ignore[no-any-return]

    def get_repos(request: Request) -> Repositories:
        return request.app.state.repos  # type: ignore[no-any-return]

    def get_plans(request: Request) -> SavedPlansStore:
        return request.app.state.plans_store  # type: ignore[no-any-return]

    def get_telemetry(request: Request) -> TelemetryRecorder:
        return request.app.state.telemetry  # type: ignore[no-any-return]

    def get_audit(request: Request) -> RuntimeAuditLog:
        return request.app.state.runtime_audit  # type: ignore[no-any-return]

    def get_contracts(request: Request) -> ContractsRegistry:
        return request.app.state.contracts  # type: ignore[no-any-return]

    router = APIRouter(prefix="/api")

    @router.get("/health", response_model=HealthResponse)
    def get_health(
        settings: AzureFoundrySettings = Depends(get_settings_dep),
    ) -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            banner=PROTOTYPE_BANNER,
            provider_configured=settings.configured,
            auth_mode=settings.auth_mode,
        )

    @router.get("/health/details", response_model=HealthDetailsResponse)
    def get_health_details(
        settings: AzureFoundrySettings = Depends(get_settings_dep),
        provider: LlmProvider = Depends(get_provider),
    ) -> HealthDetailsResponse:
        return build_health_details(
            settings=settings,
            provider=provider,
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
        )

    @router.post("/demo/reset", response_model=DemoResetResponse)
    def post_demo_reset(
        settings: AzureFoundrySettings = Depends(get_settings_dep),
        plans: SavedPlansStore = Depends(get_plans),
        audit: RuntimeAuditLog = Depends(get_audit),
        repos: Repositories = Depends(get_repos),
    ) -> DemoResetResponse:
        if not settings.demo_reset_enabled:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Demo reset is disabled. Set DEMO_RESET_ENABLED=true to enable "
                    "(development use only)."
                ),
            )
        audit_removed = audit.clear()
        plans_removed = plans.clear()
        plans.seed(
            specs=repos.seeded_plans,
            learners=repos.learners,
            assessments=repos.assessments,
            behavior=repos.behavior,
            resources=repos.resources,
        )
        return DemoResetResponse(
            status="ok",
            plans_reset=plans_removed,
            audit_reset=audit_removed,
        )

    @router.get("/dashboard/summary", response_model=DashboardSummary)
    def get_dashboard(repos: Repositories = Depends(get_repos)) -> DashboardSummary:
        return dashboard_mod.build_summary(
            learners=repos.learners,
            assessments=repos.assessments,
            behavior=repos.behavior,
        )

    @router.get("/learners", response_model=LearnersResponse)
    def get_learners_ep(repos: Repositories = Depends(get_repos)) -> LearnersResponse:
        return learners_mod.list_learner_summaries(repos.learners)

    @router.get("/assessments/summary", response_model=AssessmentsSummary)
    def get_assessments(
        school: str | None = Query(default=None),
        grade: str | None = Query(default=None),
        domain: str | None = Query(default=None),
        group: str | None = Query(default=None),
        repos: Repositories = Depends(get_repos),
    ) -> AssessmentsSummary:
        return assessments_mod.summarize(
            records=repos.assessments,
            school=school,
            grade=grade,
            domain=domain,
            group=group,
        )

    @router.get("/behavior/summary", response_model=BehaviorSummary)
    def get_behavior(repos: Repositories = Depends(get_repos)) -> BehaviorSummary:
        return behavior_mod.summarize(repos.behavior)

    @router.get("/supports/options", response_model=SupportOptions)
    def get_support_options(repos: Repositories = Depends(get_repos)) -> SupportOptions:
        labels = [(learner.learner_id, learner.display_label) for learner in repos.learners]
        return build_support_options(labels)

    @router.post(
        "/recommendations/support-plan",
        response_model=RecommendationEnvelope,
    )
    def post_recommendation(
        payload: SupportPlanRequest,
        repos: Repositories = Depends(get_repos),
        provider: LlmProvider = Depends(get_provider),
        telemetry: TelemetryRecorder = Depends(get_telemetry),
        audit: RuntimeAuditLog = Depends(get_audit),
        contracts: ContractsRegistry = Depends(get_contracts),
    ) -> RecommendationEnvelope:
        learner = next(
            (learner for learner in repos.learners if learner.learner_id == payload.learner_id),
            None,
        )
        if learner is None:
            raise HTTPException(status_code=404, detail="Unknown learner_id")

        options = build_support_options(
            [(le.learner_id, le.display_label) for le in repos.learners]
        )
        allowed_resources = tuple(
            ResourceRef(id=r.resource_id, label=r.label, kind=r.kind) for r in repos.resources
        )
        allowed_goal_ids = tuple(
            g.id for g in options.smart_goals if g.category_id == payload.category
        )
        allowed_strategy_ids = tuple(
            s.id for s in options.strategies if s.category_id == payload.category
        )

        coordinator = AgentCoordinator(
            provider=provider,
            telemetry=telemetry,
            contracts=contracts,
        )
        crequest = CoordinatorRequest(
            learner_label=learner.display_label,
            grade=learner.grade,
            school_id=learner.school_id,
            group=learner.group,
            proficiency_index=learner.proficiency_index,
            attendance_rate=learner.attendance_rate,
            behavior_index=learner.behavior_index,
            engagement_index=learner.engagement_index,
            assessment_count=sum(
                1 for a in repos.assessments if a.learner_id == learner.learner_id
            ),
            behavior_record_count=sum(
                1 for b in repos.behavior if b.learner_id == learner.learner_id
            ),
            category=payload.category,
            concern_text=payload.concern_text,
            allowed_resources=allowed_resources,
            allowed_smart_goal_ids=allowed_goal_ids,
            allowed_strategy_ids=allowed_strategy_ids,
        )
        started = time.monotonic()
        result = coordinator.run(crequest)
        duration_ms = int((time.monotonic() - started) * 1000)
        audit.append(
            endpoint="/api/recommendations/support-plan",
            context="plan-generation",
            provider_model=result.provider_model,
            duration_ms=duration_ms,
            token_estimate=sum((step.token_estimate or 0) for step in result.agent_trace),
            status=result.status,
        )
        return RecommendationEnvelope(
            status=result.status,
            error_code=result.error_code,
            error_message=result.error_message,
            recommendation=result.recommendation,
            agent_trace=result.agent_trace,
            provider_model=result.provider_model,
        )

    @router.get("/supports/plans", response_model=SavedPlansResponse)
    def get_saved_plans(plans: SavedPlansStore = Depends(get_plans)) -> SavedPlansResponse:
        rows = plans.list()
        return SavedPlansResponse(plans=rows, total=len(rows))

    @router.post("/supports/plans", response_model=SavedPlan)
    def post_saved_plan(
        payload: SavePlanRequest,
        plans: SavedPlansStore = Depends(get_plans),
    ) -> SavedPlan:
        plan = SavedPlan(
            plan_id=plans.next_plan_id(),
            learner_id=payload.learner_id,
            category=payload.category,
            concern_text=payload.concern_text,
            selected_smart_goal=payload.selected_smart_goal,
            selected_strategies=payload.selected_strategies,
            created_at=_next_iso(offset_seconds=len(plans.list()) * 47),
            recommendation=payload.recommendation,
        )
        return plans.add(plan)

    @router.get("/audit/events", response_model=AuditResponse)
    def get_audit_events(
        repos: Repositories = Depends(get_repos),
        audit: RuntimeAuditLog = Depends(get_audit),
    ) -> AuditResponse:
        seeded = audit_mod.list_events(repos.audit).events
        runtime_rows: list[AuditEvent] = audit.snapshot()
        combined = seeded + runtime_rows
        return AuditResponse(
            events=combined,
            total=len(combined),
            disclaimer=(
                "Seeded synthetic rows plus in-memory metadata for LLM calls "
                "made during the current process. No prompts, completions, "
                "raw validator critique, or secrets are stored."
            ),
        )

    app.include_router(router)
    return app


app = create_app()
