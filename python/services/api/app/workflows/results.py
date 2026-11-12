"""Data passed into and out of the workflow.

Separate module so `executors.py` and `coordinator.py` can both import these
without a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.shared.contracts import ResourceRef
from ..models import AgentTraceStep, Recommendation
from ..operations import OperationsSeries
from ..scores import AreaSeries
from .plan import PlanState

# Recorded on trace steps that completed without any model call, so a
# deterministic step is never credited to a model that did no work.
LOCAL_STEP_MODEL = "none"


@dataclass(frozen=True)
class CoordinatorRequest:
    """Everything the workflow needs. Assembled by the HTTP layer."""

    dealer_group_id: str
    dealership_label: str
    region_id: str
    segment: str
    process_score: float
    appointment_attendance_rate: float
    followup_index: float
    engagement_index: float
    area_series: AreaSeries
    operations_series: OperationsSeries
    category: str
    concern_text: str
    allowed_resources: tuple[ResourceRef, ...]
    allowed_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]


@dataclass(frozen=True)
class RunContext:
    """What identifies one run, as opposed to what it has done so far."""

    correlation_id: str
    dealer_group_id: str
    provider_model: str


@dataclass(frozen=True)
class CoordinatorResult:
    """The workflow outcome. `recommendation` is None unless status is ok."""

    status: str
    error_code: str | None
    error_message: str | None
    recommendation: Recommendation | None
    agent_trace: list[AgentTraceStep]
    provider_model: str
    correlation_id: str
    dealer_group_id: str
    evidence_count: int | None = None
    citation_count: int | None = None
    validator_status: str = ""
    # Enforcement facts for the UI receipt. None means the stage never ran, so
    # the UI renders absence. A zero here would assert the stage ran and found
    # nothing, which on a run that died early is a false claim.
    citations_proposed: int | None = None
    citations_accepted: int | None = None
    resources_proposed: int | None = None
    resources_accepted: int | None = None
    unknown_resource_ids: list[str] = field(default_factory=list)
    attempts: int | None = None
    validation_reached: bool = False
    deterministic_checks_total: int | None = None


@dataclass(frozen=True)
class StepRecord:
    """One trace row as an executor reports it, via `ctx.yield_output`.

    The coordinator adds the duration from the workflow's own
    `executor_invoked` / `executor_completed` events.
    """

    agent: str
    status: str
    provider: str
    model: str
    token_estimate: int | None = None
    issue_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    citation_count: int = 0


def failure_result(
    context: RunContext,
    plan: PlanState | None,
    trace: list[AgentTraceStep],
    *,
    status: str,
    error_code: str,
    error_message: str,
    validator_status: str = "",
) -> CoordinatorResult:
    """A finished result for a run that ended without a recommendation."""

    return CoordinatorResult(
        status=status,
        error_code=error_code,
        error_message=error_message,
        recommendation=None,
        agent_trace=trace,
        provider_model=context.provider_model,
        correlation_id=context.correlation_id,
        dealer_group_id=context.dealer_group_id,
        evidence_count=plan.evidence_count if plan else None,
        citation_count=plan.citation_count if plan else None,
        validator_status=validator_status,
        citations_proposed=plan.citations_proposed if plan else None,
        citations_accepted=plan.citations_accepted if plan else None,
        attempts=(plan.attempts or None) if plan else None,
        validation_reached=plan.validation_reached if plan else False,
        deterministic_checks_total=plan.deterministic_checks_total if plan else None,
    )


class StepFailed(Exception):
    """Abort the workflow.

    Carries the outcome and the plan as far as it got. Agent Framework
    propagates it out of the run, where the coordinator turns it into a
    `CoordinatorResult`.
    """

    def __init__(
        self, *, status: str, error_code: str, error_message: str, plan: PlanState
    ) -> None:
        super().__init__(error_code)
        self.status = status
        self.error_code = error_code
        self.error_message = error_message
        self.plan = plan
