"""Health, readiness, and the development-only demo reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..build_info import current_build_id
from ..config import (
    PROTOTYPE_BANNER,
    SERVICE_NAME,
    SERVICE_VERSION,
    AzureFoundrySettings,
)
from ..dependencies import (
    get_audit,
    get_evidence,
    get_plans,
    get_repos,
    get_runtime,
    get_settings,
    guarded,
)
from ..diagnostics import build_health_details
from ..evidence import EvidenceRetriever
from ..foundry_agents import MafAgentRuntime
from ..models import DemoResetResponse, HealthDetailsResponse, HealthResponse
from ..plans_store import SavedPlansStore
from ..repositories import Repositories
from ..runtime_audit import RuntimeAuditLog

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def get_health(settings: AzureFoundrySettings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        banner=PROTOTYPE_BANNER,
        provider_configured=settings.configured,
        foundry_auth_mode=settings.auth_mode,
        build_id=current_build_id(),
    )


@router.get("/health/details", response_model=HealthDetailsResponse, dependencies=guarded)
def get_health_details(
    settings: AzureFoundrySettings = Depends(get_settings),
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


@router.post("/demo/reset", response_model=DemoResetResponse, dependencies=guarded)
def post_demo_reset(
    settings: AzureFoundrySettings = Depends(get_settings),
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
        dealerships=repos.dealerships,
        area_scores=repos.area_scores,
        operations=repos.operations,
        resources=repos.resources,
    )
    return DemoResetResponse(status="ok", plans_reset=plans_removed, audit_reset=audit_removed)
