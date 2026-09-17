"""Entry point to the plan workflow.

The orchestration itself is a Microsoft Agent Framework graph -- see
`graph.py`, which is short enough to read in one sitting. This module only
starts a run and hands back its result.

Two things happen here that the graph cannot do for itself:

- `collect_call_metrics()` is open for the whole run, so the served model and
  token counts of every model call land in one place for the trace.
- `StepFailed` is caught. A node that cannot continue -- no evidence, a
  provider error, off-contract JSON -- raises it with a finished
  `CoordinatorResult` inside, and Agent Framework propagates the exception
  out of `workflow.run()`.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from ..config import CONCERN_TEXT_MAX_LEN, ORCHESTRATION_TOTAL_BUDGET_SECONDS
from ..contracts_registry import ContractsRegistry
from ..evidence import EvidenceRetriever
from ..foundry_agents.maf_runtime import MafAgentRuntime, collect_call_metrics
from .graph import build_plan_workflow
from .plan import PlanState
from .results import (
    LOCAL_STEP_MODEL,
    CoordinatorRequest,
    CoordinatorResult,
    RunState,
    StepFailed,
)

__all__ = ["AgentCoordinator", "CoordinatorRequest", "CoordinatorResult", "LOCAL_STEP_MODEL"]


class AgentCoordinator:
    """Runs one support-plan workflow per request."""

    def __init__(
        self,
        *,
        runtime: MafAgentRuntime,
        contracts: ContractsRegistry,
        evidence_retriever: EvidenceRetriever,
        provider_display: str,
    ) -> None:
        self._runtime = runtime
        self._contracts = contracts
        self._evidence = evidence_retriever
        self._provider_display = provider_display

    async def run(self, request: CoordinatorRequest) -> CoordinatorResult:
        with collect_call_metrics() as calls:
            state = RunState(
                correlation_id=str(uuid.uuid4()),
                dealer_group_id=request.dealer_group_id,
                provider_model=self._provider_display,
                # A wall clock for the whole request. Every step checks it
                # before starting, and clamps its own timeout to what is left.
                deadline=time.monotonic() + ORCHESTRATION_TOTAL_BUDGET_SECONDS,
                calls=calls,
            )
            built = build_plan_workflow(
                request=request,
                state=state,
                runtime=self._runtime,
                contracts=self._contracts,
                evidence_retriever=self._evidence,
                provider_display=self._provider_display,
            )

            concern = (request.concern_text or "").strip()[:CONCERN_TEXT_MAX_LEN]
            try:
                # The per-step deadline only applies to steps that check it.
                # Evidence retrieval can block inside a client call, so the
                # whole run is bounded here as well.
                events = await asyncio.wait_for(
                    built.workflow.run(PlanState(concern=concern)),
                    timeout=max(0.0, state.deadline - time.monotonic()),
                )
            except StepFailed as failure:
                return failure.result
            except TimeoutError:
                return state.failure(
                    status="orchestration_budget_exhausted",
                    error_code="ORCHESTRATION_BUDGET_EXHAUSTED",
                    error_message="Orchestration exceeded total budget.",
                )

            return _single_result(events.get_outputs(), state)


def _single_result(outputs: list[object], state: RunState) -> CoordinatorResult:
    """Exactly one terminal node may produce a result.

    Two would mean a conditional edge fired that should not have, which is
    the failure mode a shared mutable message causes. `PlanState` is frozen
    to prevent it; this is the assertion that it worked.
    """

    results = [o for o in outputs if isinstance(o, CoordinatorResult)]
    if len(results) == 1:
        return results[0]
    return state.failure(
        status="orchestration_error",
        error_code="WORKFLOW_OUTPUT_UNEXPECTED",
        error_message=(f"Workflow produced {len(results)} results; exactly one was expected."),
    )
