"""Entry point to the plan workflow.

The orchestration itself is a Microsoft Agent Framework graph -- see
`graph.py`, which is short enough to read in one sitting. This module starts
a run, reads the workflow's own event stream, and hands back its result.

From that stream it takes three things:

- the trace rows the working nodes yield as intermediate outputs,
- each node's duration, from Agent Framework's `executor_invoked` and
  `executor_completed` / `executor_failed` events,
- the one result `Finalise` or `Refuse` yields.

A node that cannot continue -- no evidence, a provider error, off-contract
JSON -- raises `StepFailed`, and Agent Framework propagates it out of the run.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import Any

from ..config import CONCERN_TEXT_MAX_LEN
from ..evidence import EvidenceRetriever
from ..foundry_agents.maf_runtime import MafAgentRuntime
from ..models import AgentTraceStep
from .graph import build_plan_workflow
from .plan import PlanState
from .results import (
    LOCAL_STEP_MODEL,
    CoordinatorRequest,
    CoordinatorResult,
    RunContext,
    StepFailed,
    StepRecord,
    failure_result,
)

__all__ = ["AgentCoordinator", "CoordinatorRequest", "CoordinatorResult", "LOCAL_STEP_MODEL"]


class AgentCoordinator:
    """Runs one support-plan workflow per request."""

    def __init__(
        self,
        *,
        runtime: MafAgentRuntime,
        evidence_retriever: EvidenceRetriever,
        provider_display: str,
    ) -> None:
        self._runtime = runtime
        self._evidence = evidence_retriever
        self._provider_display = provider_display

    async def run(self, request: CoordinatorRequest) -> CoordinatorResult:
        context = RunContext(
            correlation_id=str(uuid.uuid4()),
            dealer_group_id=request.dealer_group_id,
            provider_model=self._provider_display,
        )
        workflow = build_plan_workflow(
            request=request,
            context=context,
            runtime=self._runtime,
            evidence_retriever=self._evidence,
            provider_display=self._provider_display,
        )

        concern = (request.concern_text or "").strip()[:CONCERN_TEXT_MAX_LEN]
        trace = _Trace()
        outputs: list[object] = []
        try:
            async for event in workflow.run(PlanState(concern=concern), stream=True):
                trace.observe(event)
                if event.type == "output":
                    outputs.append(event.data)
        except StepFailed as failure:
            return failure_result(
                context,
                failure.plan,
                trace.steps(),
                status=failure.status,
                error_code=failure.error_code,
                error_message=failure.error_message,
            )

        return _single_result(outputs, context, trace.steps())


class _Trace:
    """The trace, read off the workflow's event stream.

    Each working node yields one `StepRecord` per invocation; its duration is
    the time between that node's invoked and completed (or failed) events.
    """

    def __init__(self) -> None:
        self._started: dict[str, float] = {}
        self._pending: dict[str, list[StepRecord]] = {}
        self._steps: list[AgentTraceStep] = []

    def observe(self, event: Any) -> None:
        executor_id = getattr(event, "executor_id", None)
        if event.type == "executor_invoked" and executor_id:
            self._started[executor_id] = time.monotonic()
        elif event.type == "intermediate" and isinstance(event.data, StepRecord) and executor_id:
            self._pending.setdefault(executor_id, []).append(event.data)
        elif event.type in ("executor_completed", "executor_failed") and executor_id:
            self._close(executor_id)

    def steps(self) -> list[AgentTraceStep]:
        # A run that stopped mid-node never sees that node's closing event.
        for executor_id in list(self._pending):
            self._close(executor_id)
        return list(self._steps)

    def _close(self, executor_id: str) -> None:
        started = self._started.pop(executor_id, None)
        latency_ms = int((time.monotonic() - started) * 1000) if started is not None else 0
        for record in self._pending.pop(executor_id, []):
            self._steps.append(
                AgentTraceStep(
                    agent=record.agent,
                    status=record.status,
                    provider=record.provider,
                    model=record.model,
                    latency_ms=latency_ms,
                    token_estimate=record.token_estimate,
                    issue_codes=list(record.issue_codes),
                    warning_codes=list(record.warning_codes),
                    citation_count=record.citation_count,
                )
            )


def _single_result(
    outputs: list[object], context: RunContext, trace: list[AgentTraceStep]
) -> CoordinatorResult:
    """Exactly one terminal node may produce a result.

    Two would mean a conditional edge fired that should not have, which is
    the failure mode a shared mutable message causes. `PlanState` is frozen
    to prevent it; this is the assertion that it worked.
    """

    results = [o for o in outputs if isinstance(o, CoordinatorResult)]
    if len(results) == 1:
        return replace(results[0], agent_trace=trace)
    return failure_result(
        context,
        None,
        trace,
        status="orchestration_error",
        error_code="WORKFLOW_OUTPUT_UNEXPECTED",
        error_message=f"Workflow produced {len(results)} results; exactly one was expected.",
    )
