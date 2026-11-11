"""One agent hop: budget check, invoke, trace, typed failure.

Every step does the same three things around the actual call, so they live
here once instead of being repeated inline for each agent.

Nothing here emits telemetry. Agent Framework instruments the graph itself —
`executor.process`, `edge_group.process` and the gen_ai model spans — so a
second hand-written event stream would only be a lower-fidelity copy. The
trace this builds is a different thing: it goes in the API response and the
UI renders it.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ..contracts_registry import ContractsRegistry, ContractValidationError
from ..foundry_agents.errors import FoundryProviderError
from ..foundry_agents.maf_runtime import PROVIDER_ID
from ..models import AgentTraceStep
from .failures import classify_provider_error, invalid_json_code, safe_message
from .results import LOCAL_STEP_MODEL, RunState, StepFailed

_T = TypeVar("_T")


@dataclass(frozen=True)
class StepOutcome:
    """How a completed step should appear in the trace."""

    status: str = "ok"
    issue_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    citation_count: int = 0


class StepRunner:
    """Runs one workflow step and records what happened.

    Raises `StepFailed` rather than returning a result union, so the caller
    reads as a sequence of handoffs instead of a chain of type checks.
    """

    def __init__(
        self,
        *,
        state: RunState,
        contracts: ContractsRegistry,
    ) -> None:
        self._state = state
        self._contracts = contracts

    async def call(
        self,
        agent_name: str,
        invoke: Callable[[], Awaitable[_T]],
        *,
        outcome: Callable[[_T], StepOutcome] | None = None,
    ) -> _T:
        """Invoke one agent, or raise `StepFailed` with a typed outcome.

        `outcome` lets a step name its own result: the validator reports
        passed/failed rather than "ok".
        """

        self._require_budget(agent_name)
        started = time.monotonic()
        calls_before = len(self._state.calls)
        try:
            result = await invoke()
        except FoundryProviderError as exc:
            status, code = classify_provider_error(exc)
            self._fail_step(
                agent_name,
                status=status,
                code=code,
                latency_ms=_elapsed_ms(started),
                message=safe_message(status),
            )
        except ValueError as exc:
            # Never put exception text in an issue code. Pydantic quotes the
            # offending value, which is model output derived from a dealer
            # group's evidence, and issue codes travel to the response.
            self._fail_step(
                agent_name,
                status="invalid_model_json",
                code=invalid_json_code(exc),
                latency_ms=_elapsed_ms(started),
                message="Remote agent returned invalid or off-schema JSON.",
                error_code="AGENT_INVALID_JSON",
            )

        latency_ms = _elapsed_ms(started)
        served_model, tokens = self._state.drain_calls(calls_before)
        step = outcome(result) if outcome else StepOutcome()
        self._state.trace.append(
            AgentTraceStep(
                agent=agent_name,
                status=step.status,
                provider=PROVIDER_ID,
                model=served_model or LOCAL_STEP_MODEL,
                latency_ms=latency_ms,
                token_estimate=tokens,
                issue_codes=list(step.issue_codes),
                warning_codes=list(step.warning_codes),
                citation_count=step.citation_count,
            )
        )
        return result

    def check_protocol(self, *, schema_name: str, message: dict[str, Any], agent_name: str) -> None:
        """Validate an inter-agent message, or raise `StepFailed`."""

        try:
            self._contracts.validate(schema_name, message)
        except ContractValidationError as exc:
            self._fail_step(
                agent_name,
                status="invalid_model_json",
                code="PROTOCOL_VALIDATION_FAILED",
                latency_ms=0,
                message=(f"Message failed protocol validation ({schema_name}: {exc.safe_reason})."),
                error_code="PROTOCOL_VALIDATION_FAILED",
            )

    def trace_local(self, step: AgentTraceStep) -> None:
        """Record a step that made no model call."""

        self._state.trace.append(step)

    def _require_budget(self, agent_name: str) -> None:
        if time.monotonic() < self._state.deadline:
            return
        self._fail_step(
            agent_name,
            status="orchestration_budget_exhausted",
            code="ORCHESTRATION_BUDGET_EXHAUSTED",
            latency_ms=0,
            message="Orchestration exceeded total budget.",
            error_code="ORCHESTRATION_BUDGET_EXHAUSTED",
        )

    def _fail_step(
        self,
        agent_name: str,
        *,
        status: str,
        code: str,
        latency_ms: int,
        message: str,
        error_code: str | None = None,
    ) -> None:
        self._state.trace.append(
            AgentTraceStep(
                agent=agent_name,
                status=status,
                provider=PROVIDER_ID,
                model=self._state.provider_model,
                latency_ms=latency_ms,
                token_estimate=None,
                issue_codes=[code],
            )
        )
        # `from None` is a privacy control, not style. Agent Framework records
        # the escaping exception on the executor and workflow spans, and a
        # formatted traceback includes the chained cause -- for a Pydantic
        # failure that is `input_value=<model output>`. Breaking the chain
        # keeps the span to the typed code.
        raise StepFailed(
            self._state.failure(
                status=status,
                error_code=error_code or code,
                error_message=message,
            )
        ) from None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
