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
    evidence_count: int = 0
    citation_count: int = 0
    validator_status: str = ""


@dataclass
class RunState:
    """Mutable per-request state: what happened so far."""

    correlation_id: str
    dealer_group_id: str
    provider_model: str
    deadline: float
    trace: list[AgentTraceStep] = field(default_factory=list)
    calls: list[CallMetrics] = field(default_factory=list)
    evidence_count: int = 0
    citation_count: int = 0

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
        )


class StepFailed(Exception):
    """Abort the workflow with a finished result.

    Raising rather than returning keeps `_sequence` readable: every line
    there is an agent handoff, not a check on whether the last one worked.
    """

    def __init__(self, result: CoordinatorResult) -> None:
        super().__init__(result.error_code or result.status)
        self.result = result
