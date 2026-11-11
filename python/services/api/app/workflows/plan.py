"""What travels the edges of the plan workflow.

Frozen, and carrying domain data only. Two reasons, both learned the hard
way:

- Several outgoing edges are handed the *same* message object and evaluate
  their conditions independently. A step that mutates it can make a sibling
  condition fire that should not, so one run yields two results.
- Executor lifecycle events copy the values that pass through them. A
  service client or a request object in here would be copied with them, and
  prompt text would reach spans that are meant to stay metadata-only.

Everything that is not domain data -- the runtime, the request, the retriever
-- is held on the executors instead, which are built fresh per request.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..agents.shared.contracts import (
    DataAnalystOutput,
    SupportRecommendationDraft,
    ValidatorReport,
)
from ..evidence import EvidenceBundle

# One repair attempt. The second failure is a refusal, not a third try.
MAX_RECOMMENDER_ATTEMPTS = 2


@dataclass(frozen=True)
class PlanState:
    """One request's progress through the graph.

    The optional fields are filled in by the node that produces them. The
    `require_*` accessors exist because the graph guarantees the order --
    nothing reaches `Validate` without a draft -- but the type checker cannot
    see that through the edges.
    """

    concern: str
    evidence: EvidenceBundle | None = None
    analysis: DataAnalystOutput | None = None
    draft: SupportRecommendationDraft | None = None
    report: ValidatorReport | None = None
    attempts: int = 0

    def with_(self, **changes: Any) -> PlanState:
        return replace(self, **changes)

    def require_evidence(self) -> EvidenceBundle:
        return _required(self.evidence, "evidence")

    def require_analysis(self) -> DataAnalystOutput:
        return _required(self.analysis, "analysis")

    def require_draft(self) -> SupportRecommendationDraft:
        return _required(self.draft, "draft")

    def require_report(self) -> ValidatorReport:
        return _required(self.report, "report")


def _required[T](value: T | None, name: str) -> T:
    if value is None:
        raise RuntimeError(f"plan reached a node without {name}; the graph is mis-wired")
    return value


def passed(state: PlanState) -> bool:
    """Edge condition: the validator accepted the draft."""

    return state.report is not None and state.report.passed


def needs_repair(state: PlanState) -> bool:
    """Edge condition: rejected, and a repair attempt is still available."""

    return (
        state.report is not None
        and not state.report.passed
        and state.attempts < MAX_RECOMMENDER_ATTEMPTS
    )


def repair_exhausted(state: PlanState) -> bool:
    """Edge condition: rejected again. No recommendation is returned."""

    return (
        state.report is not None
        and not state.report.passed
        and state.attempts >= MAX_RECOMMENDER_ATTEMPTS
    )
