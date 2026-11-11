"""Data passed into and out of the workflow, plus the per-run scratch state.

Separate module so `steps.py` and `coordinator.py` can both import these
without a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.shared.contracts import ResourceRef
from ..foundry_agents.maf_runtime import CallMetrics
from ..models import AgentTraceStep, Recommendation
from ..operations import OperationsSeries
from ..scores import AreaSeries

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


@dataclass
class RunState:
    """Mutable per-request state: what happened so far."""

    correlation_id: str
    dealer_group_id: str
    provider_model: str
    deadline: float
    trace: list[AgentTraceStep] = field(default_factory=list)
    calls: list[CallMetrics] = field(default_factory=list)
    evidence_count: int | None = None
    citation_count: int | None = None
    # `citations_proposed` is the only one of these the executor cannot see:
    # the model's own id list is dropped inside the recommender wrapper.
    citations_proposed: int | None = None
    citations_accepted: int | None = None
    attempts: int | None = None
    validation_reached: bool = False
    deterministic_checks_total: int | None = None

    def drain_calls(self, start: int) -> tuple[str, int | None]:
        """Model that served the newest calls, and their total token count."""

        new = self.calls[start:]
        if not new:
            return "", None
        counted = [
            (c.input_tokens or 0) + (c.output_tokens or 0)
            for c in new
            if c.input_tokens is not None or c.output_tokens is not None
        ]
        return new[-1].model, (sum(counted) if counted else None)

    def failure(
        self,
        *,
        status: str,
        error_code: str,
        error_message: str,
        validator_status: str = "",
    ) -> CoordinatorResult:
        return CoordinatorResult(
            status=status,
            error_code=error_code,
            error_message=error_message,
            recommendation=None,
            agent_trace=self.trace,
            provider_model=self.provider_model,
            correlation_id=self.correlation_id,
            dealer_group_id=self.dealer_group_id,
            evidence_count=self.evidence_count,
            citation_count=self.citation_count,
            validator_status=validator_status,
            citations_proposed=self.citations_proposed,
            citations_accepted=self.citations_accepted,
            attempts=self.attempts,
            validation_reached=self.validation_reached,
            deterministic_checks_total=self.deterministic_checks_total,
        )


class StepFailed(Exception):
    """Abort the workflow with a finished result.

    Raising rather than returning keeps `_sequence` readable: every line
    there is an agent handoff, not a check on whether the last one worked.
    """

    def __init__(self, result: CoordinatorResult) -> None:
        super().__init__(result.error_code or result.status)
        self.result = result
