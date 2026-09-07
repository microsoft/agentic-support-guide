"""FastAPI application entry point.

All routes are mounted under /api. OpenAPI is served at /api/openapi.json
and the interactive docs at /api/docs. CORS is an explicit allowlist,
overridable with ALLOWED_ORIGINS.

Runtime shape: every recommendation request is orchestrated by the
AgentCoordinator, which invokes three Azure AI Foundry agent roles through
Microsoft Agent Framework. There is no local model call and no local
fallback.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import assessments as assessments_mod
from . import audit as audit_mod
from . import behavior as behavior_mod
from . import dashboard as dashboard_mod
from . import learners as learners_mod
from .agents.shared.contracts import ResourceRef
from .build_info import current_build_id
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
    FoundryResponsesClientFactory,
    MafAgentRuntime,
    default_credential_factory,
    load_role_definitions,
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

PROVIDER_DISPLAY_CONFIGURED = "Azure AI Foundry (Agent Framework, prompt agents)"

# Vite dev server. Override with a comma-separated ALLOWED_ORIGINS when the
# API is served anywhere other than the local dev proxy.
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


def _allowed_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    configured = [o.strip() for o in raw.split(",") if o.strip()]
    return configured or list(DEFAULT_ALLOWED_ORIGINS)


def _build_evidence_retriever() -> EvidenceRetriever:
    """Fixtures or Foundry IQ, chosen by EVIDENCE_SOURCE.

    Fixtures are the default so tests and CI stay offline and free. Setting
    EVIDENCE_SOURCE=foundry_iq is what makes the app serve real retrieved
    evidence instead of in-memory data.
    """

    source = os.environ.get("EVIDENCE_SOURCE", "fixtures").strip().lower()
    if source in ("", "fixtures"):
        return FixtureEvidenceRetriever()
    if source == "foundry_iq":
        from .evidence.foundry_iq import FoundryIQEvidenceRetriever

        return FoundryIQEvidenceRetriever(
            endpoint=os.environ.get("AZURE_SEARCH_ENDPOINT", ""),
            knowledge_base=os.environ.get("FOUNDRY_IQ_KNOWLEDGE_BASE", ""),
            index_name=os.environ.get("FOUNDRY_IQ_INDEX", ""),
        )
    raise ValueError(f"Unknown EVIDENCE_SOURCE {source!r}. Use 'fixtures' or 'foundry_iq'.")


PROVIDER_DISPLAY_UNCONFIGURED = "unconfigured (Azure AI Foundry not set up)"


def _next_iso(offset_seconds: int) -> str:
    base = datetime.strptime(BASE_TIMESTAMP, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (base + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_runtime(
    settings: AzureFoundrySettings,
    client_factory: Callable[[str], Any] | None,
) -> MafAgentRuntime | None:
    """Assemble role definitions from agent.md + per-role model deployments.

    There are no persisted agents to look up: a role is available when its
    definition loads and its model deployment env var is set.
    """

    if not settings.project_endpoint:
        return None
    roles = load_role_definitions()
    if not roles:
        return None
    factory = (
        client_factory(settings.project_endpoint)
        if client_factory is not None
        else FoundryResponsesClientFactory(
            project_endpoint=settings.project_endpoint,
            credential_factory=default_credential_factory,
        )
    )
    return MafAgentRuntime(
        roles=roles,
        client_factory=factory,
        run_timeout_seconds=FOUNDRY_RUN_TIMEOUT_SECONDS,
    )


LEARNERS_RESPONSE_MODEL = "LearnersResponse"


def create_app(
    *,
    runtime: MafAgentRuntime | None = None,
    client_factory: Callable[[str], Any] | None = None,
    evidence_retriever: EvidenceRetriever | None = None,
) -> FastAPI:
    settings = load_foundry_settings()
    app = FastAPI(
        title="Agentic Support Guide API",
        description=(
            "Prototype API demonstrating three collaborating agents. The "
            "coordinator composes each role in-process with Microsoft Agent "
            "Framework and calls Azure AI Foundry models; the same "
            "definitions are also published to Foundry as prompt agents. "
            "Synthetic data only."
        ),
        version=SERVICE_VERSION,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # Explicit allowlist rather than relying on the Vite dev proxy: if this
    # app is ever served directly, no-CORS-middleware means any origin can
    # call it. Credentials are deliberately not allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
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
    if runtime is None:
        runtime = _build_runtime(settings, client_factory)
    if evidence_retriever is None:
        evidence_retriever = _build_evidence_retriever()
    contracts = load_registry()

    app.state.settings = settings
    app.state.repos = repos
    app.state.plans_store = plans_store
    app.state.telemetry = telemetry
    app.state.runtime_audit = runtime_audit
    app.state.runtime = runtime
    app.state.evidence_retriever = evidence_retriever
    app.state.contracts = contracts

    def get_runtime(request: Request) -> MafAgentRuntime | None:
        return request.app.state.runtime  # type: ignore[no-any-return]

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
            build_id=current_build_id(),
        )

    @router.get("/health/details", response_model=HealthDetailsResponse)
    def get_health_details(
        settings: AzureFoundrySettings = Depends(get_settings_dep),
        runtime: MafAgentRuntime | None = Depends(get_runtime),
        evidence: EvidenceRetriever = Depends(get_evidence),
    ) -> HealthDetailsResponse:
        return build_health_details(
            settings=settings,
            runtime=runtime,
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
        telemetry: TelemetryRecorder = Depends(get_telemetry),
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
        telemetry.clear()
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
    async def post_recommendation(
        payload: SupportPlanRequest,
        repos: Repositories = Depends(get_repos),
        runtime: MafAgentRuntime | None = Depends(get_runtime),
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

        if runtime is None:
            return RecommendationEnvelope(
                status="provider_missing",
                error_code="AGENT_PROVIDER_MISSING",
                error_message=(
                    "Azure AI Foundry Agent Service is not configured or bindings "
                    "are missing. Run scripts/validate_agent_definitions.py."
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
            runtime=runtime,
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
        result = await coordinator.run(crequest)
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
