"""FastAPI application entry point.

All routes are mounted under /api. OpenAPI is served at /api/openapi.json
and the interactive docs at /api/docs. There is no CORS middleware because
the frontend uses the Vite dev proxy.

Runtime shape: every recommendation request is orchestrated by the
AgentCoordinator, which invokes three remote Azure AI Foundry Agent
Service assistants through FoundryRemoteAgentAdapter. There is no local
model call and no local fallback.
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
    FOUNDRY_RUN_TIMEOUT_SECONDS,
    PROTOTYPE_BANNER,
    SERVICE_NAME,
    SERVICE_VERSION,
    AzureFoundrySettings,
    load_foundry_settings,
)
from .contracts_registry import ContractsRegistry, load_registry
from .diagnostics import build_health_details
from .evidence import EvidenceRetriever, FixtureEvidenceRetriever
from .foundry_agents import (
    FoundryAgentClient,
    FoundryAgentClientProtocol,
    FoundryRemoteAgentAdapter,
    load_bindings,
)
from .human_review import (
    HumanReviewState,
    InvalidReviewTransitionError,
    ReviewTransitionAuditEntry,
    transition,
)
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
    ReviewTransitionRequest,
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

PROVIDER_DISPLAY_CONFIGURED = "Azure AI Foundry Agent Service (remote agents)"
PROVIDER_DISPLAY_UNCONFIGURED = "unconfigured (Azure AI Foundry Agent Service not set up)"


def _next_iso(offset_seconds: int) -> str:
    base = datetime.strptime(BASE_TIMESTAMP, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (base + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_client_factory(endpoint: str) -> FoundryAgentClientProtocol:
    from azure.identity import DefaultAzureCredential

    return FoundryAgentClient(endpoint=endpoint, credential=DefaultAzureCredential())


def _build_adapter(
    settings: AzureFoundrySettings,
    client_factory: Callable[[str], FoundryAgentClientProtocol],
) -> FoundryRemoteAgentAdapter | None:
    if not settings.project_endpoint:
        return None
    bindings = load_bindings()
    if not bindings:
        return None
    client = client_factory(settings.project_endpoint)
    return FoundryRemoteAgentAdapter(
        client=client,
        bindings=bindings,
        project_endpoint=settings.project_endpoint,
        run_timeout_seconds=FOUNDRY_RUN_TIMEOUT_SECONDS,
    )


LEARNERS_RESPONSE_MODEL = "LearnersResponse"


def create_app(
    *,
    adapter: FoundryRemoteAgentAdapter | None = None,
    client_factory: Callable[[str], FoundryAgentClientProtocol] | None = None,
    evidence_retriever: EvidenceRetriever | None = None,
) -> FastAPI:
    settings = load_foundry_settings()
    app = FastAPI(
        title="Agentic Support Guide API",
        description=(
            "Prototype API demonstrating three collaborating agents hosted "
            "in Azure AI Foundry Agent Service. Synthetic data only."
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
    if adapter is None:
        adapter = _build_adapter(settings, client_factory or _default_client_factory)
    if evidence_retriever is None:
        evidence_retriever = FixtureEvidenceRetriever()
    contracts = load_registry()

    app.state.settings = settings
    app.state.repos = repos
    app.state.plans_store = plans_store
    app.state.telemetry = telemetry
    app.state.runtime_audit = runtime_audit
    app.state.adapter = adapter
    app.state.evidence_retriever = evidence_retriever
    app.state.contracts = contracts

    def get_adapter(request: Request) -> FoundryRemoteAgentAdapter | None:
        return request.app.state.adapter  # type: ignore[no-any-return]

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

    def get_evidence(request: Request) -> EvidenceRetriever:
        return request.app.state.evidence_retriever  # type: ignore[no-any-return]

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
        adapter: FoundryRemoteAgentAdapter | None = Depends(get_adapter),
        evidence: EvidenceRetriever = Depends(get_evidence),
    ) -> HealthDetailsResponse:
        return build_health_details(
            settings=settings,
            adapter=adapter,
            evidence_retriever=evidence,
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
        adapter: FoundryRemoteAgentAdapter | None = Depends(get_adapter),
        telemetry: TelemetryRecorder = Depends(get_telemetry),
        audit: RuntimeAuditLog = Depends(get_audit),
        contracts: ContractsRegistry = Depends(get_contracts),
        evidence: EvidenceRetriever = Depends(get_evidence),
    ) -> RecommendationEnvelope:
        learner = next(
            (learner for learner in repos.learners if learner.learner_id == payload.learner_id),
            None,
        )
        if learner is None:
            raise HTTPException(status_code=404, detail="Unknown learner_id")

        if adapter is None:
            return RecommendationEnvelope(
                status="provider_missing",
                error_code="AGENT_PROVIDER_MISSING",
                error_message=(
                    "Azure AI Foundry Agent Service is not configured or bindings "
                    "are missing. Run scripts/sync_foundry_agents.py --apply."
                ),
                recommendation=None,
                agent_trace=[],
                provider_model=PROVIDER_DISPLAY_UNCONFIGURED,
                correlation_id="",
                district_id=payload.district_id,
            )

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
            adapter=adapter,
            telemetry=telemetry,
            contracts=contracts,
            evidence_retriever=evidence,
            provider_display=PROVIDER_DISPLAY_CONFIGURED,
        )
        crequest = CoordinatorRequest(
            district_id=payload.district_id,
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
            correlation_id=result.correlation_id,
            district_id=result.district_id,
            evidence_count=result.evidence_count,
            citation_count=result.citation_count,
            validator_status=result.validator_status,
        )
        return RecommendationEnvelope(
            status=result.status,
            error_code=result.error_code,
            error_message=result.error_message,
            recommendation=result.recommendation,
            agent_trace=result.agent_trace,
            provider_model=result.provider_model,
            correlation_id=result.correlation_id,
            district_id=result.district_id,
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
            district_id=payload.district_id,
            category=payload.category,
            concern_text=payload.concern_text,
            selected_smart_goal=payload.selected_smart_goal,
            selected_strategies=payload.selected_strategies,
            created_at=_next_iso(offset_seconds=len(plans.list()) * 47),
            recommendation=payload.recommendation,
            human_review_state=HumanReviewState.PENDING_REVIEW.value,
        )
        return plans.add(plan)

    @router.post("/supports/plans/{plan_id}/review", response_model=SavedPlan)
    def post_plan_review(
        plan_id: str,
        payload: ReviewTransitionRequest,
        plans: SavedPlansStore = Depends(get_plans),
        audit: RuntimeAuditLog = Depends(get_audit),
    ) -> SavedPlan:
        plan = plans.get(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Unknown plan_id")
        try:
            new_state = transition(
                HumanReviewState(plan.human_review_state),
                HumanReviewState(payload.to_state),
            )
        except InvalidReviewTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        updated = plan.model_copy(update={"human_review_state": new_state.value})
        plans.replace(updated)
        audit.append_review_transition(
            ReviewTransitionAuditEntry(
                correlation_id=plan_id,
                district_id=plan.district_id,
                user_label=payload.user_label,
                timestamp=_next_iso(offset_seconds=len(plans.list()) * 47),
                previous_state=plan.human_review_state,
                new_state=new_state.value,
                validator_verdict="post-hoc",
                evidence_count=len(plan.recommendation.citations),
            )
        )
        return updated

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
