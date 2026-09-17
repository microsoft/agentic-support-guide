"""Read-only views over the synthetic dataset.

The roster has no dealer group dimension: `Dealership`, `AreaScoreRecord`
and `OperationsRecord` carry no `dealer_group_id`, so these endpoints have
nothing to filter on and every caller sees the same network. They still
require a key, declared on the route rather than as a parameter because the
handler has no use for the value. Tracked in docs/security-and-privacy.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import dashboard as dashboard_mod
from .. import dealerships as dealerships_mod
from .. import operations as operations_mod
from .. import scores as scores_mod
from ..dependencies import get_repos, guarded
from ..models import (
    DashboardSummary,
    DealershipsResponse,
    OperationsSummary,
    ScoresSummary,
)
from ..repositories import Repositories

router = APIRouter(prefix="/api")


@router.get("/dashboard/summary", response_model=DashboardSummary, dependencies=guarded)
def get_dashboard(repos: Repositories = Depends(get_repos)) -> DashboardSummary:
    return dashboard_mod.build_summary(
        dealerships=repos.dealerships,
        area_scores=repos.area_scores,
        operations=repos.operations,
    )


@router.get("/dealerships", response_model=DealershipsResponse, dependencies=guarded)
def get_dealerships(repos: Repositories = Depends(get_repos)) -> DealershipsResponse:
    return dealerships_mod.list_dealership_summaries(repos.dealerships)


@router.get("/scores/summary", response_model=ScoresSummary, dependencies=guarded)
def get_scores(
    region: str | None = Query(default=None),
    process_area: str | None = Query(default=None),
    segment: str | None = Query(default=None),
    repos: Repositories = Depends(get_repos),
) -> ScoresSummary:
    return scores_mod.summarize(
        records=repos.area_scores,
        region=region,
        process_area=process_area,
        segment=segment,
    )


@router.get("/operations/summary", response_model=OperationsSummary, dependencies=guarded)
def get_operations(repos: Repositories = Depends(get_repos)) -> OperationsSummary:
    return operations_mod.summarize(repos.operations)
