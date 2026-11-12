"""Saving plans and moving them through human review.

Split from `supports.py` because these routes never touch a model: they are
storage and state transitions over plans a person already generated.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from ..dealer_groups import KNOWN_DEALER_GROUPS
from ..dependencies import get_audit, get_plans, guarded
from ..human_review import (
    HumanReviewState,
    InvalidReviewTransitionError,
    ReviewTransitionAuditEntry,
    transition,
)
from ..models import (
    ReviewTransitionRequest,
    SavedPlan,
    SavedPlansResponse,
    SavePlanRequest,
)
from ..plans_store import SavedPlansStore
from ..runtime_audit import RuntimeAuditLog

router = APIRouter(prefix="/api")


def _utc_now_iso() -> str:
    """Wall-clock time, because these events actually happen now.

    Seeded demo rows are dated from BASE_TIMESTAMP so they stay deterministic.
    Real saves and review transitions must not be: doing that put live audit
    rows in January 2026 and gave two plans the same timestamp after a reset.
    """

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/supports/plans", response_model=SavedPlansResponse, dependencies=guarded)
def get_saved_plans(plans: SavedPlansStore = Depends(get_plans)) -> SavedPlansResponse:
    rows = plans.list()
    return SavedPlansResponse(plans=rows, total=len(rows))


@router.post("/supports/plans", response_model=SavedPlan, dependencies=guarded)
def post_saved_plan(
    payload: SavePlanRequest, plans: SavedPlansStore = Depends(get_plans)
) -> SavedPlan:
    # SavePlanRequest only proves the body agrees with itself: both the request
    # and the embedded recommendation could name a group that does not exist.
    if payload.dealer_group_id not in KNOWN_DEALER_GROUPS:
        raise HTTPException(status_code=404, detail="Unknown dealer_group_id")
    plan = SavedPlan(
        plan_id=plans.next_plan_id(),
        dealership_id=payload.dealership_id,
        dealer_group_id=payload.dealer_group_id,
        category=payload.category,
        concern_text=payload.concern_text,
        selected_goal=payload.selected_goal,
        selected_strategies=payload.selected_strategies,
        created_at=_utc_now_iso(),
        recommendation=payload.recommendation,
        human_review_state=HumanReviewState.PENDING_REVIEW.value,
    )
    return plans.add(plan)


@router.post("/supports/plans/{plan_id}/review", response_model=SavedPlan, dependencies=guarded)
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
            # A review happens long after the run, so the run's uuid4 is gone.
            # This row correlates on the plan id instead.
            correlation_id=plan_id,
            dealer_group_id=plan.dealer_group_id,
            # No caller identity exists, so attribution is honest about that
            # rather than recording a name the body supplied.
            user_label="web-tier",
            timestamp=_utc_now_iso(),
            previous_state=plan.human_review_state,
            new_state=new_state.value,
            validator_verdict="post-hoc",
            evidence_count=len(plan.recommendation.citations),
        )
    )
    return updated
