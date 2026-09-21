"""The route that runs the agent workflow.

`post_recommendation` resolves the dealership, widens the HTTP request into a
`CoordinatorRequest`, and records the outcome. The orchestration itself -- who
is called, in what order, and what happens when a step fails -- lives in
`app/workflows/coordinator.py`.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from .. import operations as operations_mod
from .. import scores as scores_mod
from ..agents.shared.contracts import ResourceRef
from ..config import PROVIDER_DISPLAY_CONFIGURED, PROVIDER_DISPLAY_UNCONFIGURED
from ..contracts_registry import ContractsRegistry
from ..dealer_groups import KNOWN_DEALER_GROUPS
from ..dependencies import (
    get_audit,
    get_contracts,
    get_evidence,
    get_repos,
    get_runtime,
    guarded,
)
from ..evidence import EvidenceRetriever
from ..foundry_agents import MafAgentRuntime
from ..mock_data import Dealership
from ..models import RecommendationEnvelope, SupportOptions, SupportPlanRequest
from ..repositories import Repositories
from ..runtime_audit import RuntimeAuditLog
from ..supports import build_support_options
from ..workflows import AgentCoordinator
from ..workflows.coordinator import CoordinatorRequest

router = APIRouter(prefix="/api")


@router.get("/supports/options", response_model=SupportOptions, dependencies=guarded)
def get_support_options(repos: Repositories = Depends(get_repos)) -> SupportOptions:
    labels = [(d.dealership_id, d.display_label) for d in repos.dealerships]
    return build_support_options(labels, dealer_groups=list(KNOWN_DEALER_GROUPS))


def _coordinator_request(
    payload: SupportPlanRequest, dealership: Dealership, repos: Repositories
) -> CoordinatorRequest:
    """Widen the HTTP request into everything the workflow needs.

    The allowed catalogs are resolved here, not by the model: the recommender
    may only cite IDs this function hands it.
    """

    options = build_support_options(
        [(d.dealership_id, d.display_label) for d in repos.dealerships],
        dealer_groups=list(KNOWN_DEALER_GROUPS),
    )
    return CoordinatorRequest(
        dealer_group_id=payload.dealer_group_id,
        dealership_label=dealership.display_label,
        region_id=dealership.region_id,
        segment=dealership.segment,
        process_score=dealership.process_score,
        appointment_attendance_rate=dealership.appointment_attendance_rate,
        followup_index=dealership.followup_index,
        engagement_index=dealership.engagement_index,
        area_series=scores_mod.series_for(repos.area_scores, dealership.dealership_id),
        operations_series=operations_mod.series_for(repos.operations, dealership.dealership_id),
        category=payload.category,
        concern_text=payload.concern_text,
        allowed_resources=tuple(
            ResourceRef(id=r.resource_id, label=r.label, kind=r.kind) for r in repos.resources
        ),
        allowed_goal_ids=tuple(g.id for g in options.goals if g.category_id == payload.category),
        allowed_strategy_ids=tuple(
            s.id for s in options.strategies if s.category_id == payload.category
        ),
    )


@router.post(
    "/recommendations/support-plan",
    response_model=RecommendationEnvelope,
    dependencies=guarded,
)
async def post_recommendation(
    payload: SupportPlanRequest,
    repos: Repositories = Depends(get_repos),
    runtime: MafAgentRuntime | None = Depends(get_runtime),
    audit: RuntimeAuditLog = Depends(get_audit),
    contracts: ContractsRegistry = Depends(get_contracts),
    evidence: EvidenceRetriever = Depends(get_evidence),
) -> RecommendationEnvelope:
    dealership = next(
        (d for d in repos.dealerships if d.dealership_id == payload.dealership_id), None
    )
    if dealership is None:
        raise HTTPException(status_code=404, detail="Unknown dealership_id")
    # Retrieval is already exact-match scoped, so an unknown group returns an
    # empty bundle and the run fails as evidence_missing after two model
    # calls. Rejecting it here makes the boundary explicit and free.
    if payload.dealer_group_id not in KNOWN_DEALER_GROUPS:
        raise HTTPException(status_code=404, detail="Unknown dealer_group_id")

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
            dealer_group_id=payload.dealer_group_id,
        )

    coordinator = AgentCoordinator(
        runtime=runtime,
        contracts=contracts,
        evidence_retriever=evidence,
        provider_display=PROVIDER_DISPLAY_CONFIGURED,
    )
    request = _coordinator_request(payload, dealership, repos)
    # Timed around the workflow only, so the audited duration stays comparable
    # to the sum of the step durations in the trace.
    started = time.monotonic()
    result = await coordinator.run(request)

    audit.append(
        endpoint="/api/recommendations/support-plan",
        context="plan-generation",
        provider_model=result.provider_model,
        duration_ms=int((time.monotonic() - started) * 1000),
        token_estimate=sum((step.token_estimate or 0) for step in result.agent_trace),
        status=result.status,
        correlation_id=result.correlation_id,
        dealer_group_id=result.dealer_group_id,
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
        dealer_group_id=result.dealer_group_id,
        evidence_count=result.evidence_count,
        citation_count=result.citation_count,
        citations_proposed=result.citations_proposed,
        citations_accepted=result.citations_accepted,
        resources_proposed=result.resources_proposed,
        resources_accepted=result.resources_accepted,
        unknown_resource_ids=result.unknown_resource_ids,
        validator_status=result.validator_status,
        validation_reached=result.validation_reached,
        attempts=result.attempts,
        deterministic_checks_total=result.deterministic_checks_total,
    )
