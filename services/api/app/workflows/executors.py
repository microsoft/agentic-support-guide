"""The six nodes of the plan workflow.

One class per node. Each one is thin: take the `PlanState` off the edge, do
one job, send the next `PlanState`. `graph.py` wires them together.

Every node gets the same `PlanRun` -- the request, the run's mutable
bookkeeping, and the `StepRunner` that instruments each agent call. These are
built fresh per request, because a `Workflow` instance refuses concurrent
runs and these hold per-request state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Never

from agent_framework import Executor, WorkflowContext, handler

from ..agents.data_analyst import DataAnalystAgent, DataAnalystContext
from ..agents.data_analyst.agent import AGENT_NAME as DATA_ANALYST_NAME
from ..agents.shared.contracts import CONTRACT_VERSION
from ..agents.support_recommender import (
    SupportRecommendationAgent,
    SupportRecommenderContext,
)
from ..agents.support_recommender.agent import AGENT_NAME as RECOMMENDER_NAME
from ..agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from ..agents.validator.agent import AGENT_NAME as VALIDATOR_NAME
from ..agents.validator.checks import DETERMINISTIC_CHECKS
from ..evidence import EvidenceRequest, EvidenceRetrievalError, EvidenceRetriever
from ..models import AgentTraceStep
from . import envelopes
from .assembly import build_recommendation
from .plan import PlanState
from .results import CoordinatorRequest, CoordinatorResult, RunState, StepFailed
from .steps import StepOutcome, StepRunner

MAX_REPAIR_GUIDANCE_CHARS = 800


@dataclass(frozen=True)
class PlanRun:
    """Everything a node needs that is not on the edge."""

    request: CoordinatorRequest
    state: RunState
    step: StepRunner

    def check_handoff(
        self, *, schema: str, source: str, target: str, payload: dict[str, object], agent: str
    ) -> None:
        """Validate one inter-agent message, or raise `StepFailed`."""

        self.step.check_protocol(
            schema_name=schema,
            message=envelopes.envelope(
                source_agent=source,
                target_agent=target,
                payload=payload,
                correlation_id=self.state.correlation_id,
            ),
            agent_name=agent,
        )


class RetrieveEvidence(Executor):
    """Grounding, before any model call. An empty bundle stops the run."""

    def __init__(self, run: PlanRun, retriever: EvidenceRetriever) -> None:
        super().__init__(id="retrieve-evidence")
        self._run = run
        self._retriever = retriever

    @handler
    async def retrieve(self, plan: PlanState, ctx: WorkflowContext[PlanState]) -> None:
        provider = getattr(self._retriever, "provider_name", "unknown")
        model = getattr(self._retriever, "provider_model", "unknown")
        started = time.monotonic()
        request = self._run.request

        try:
            bundle = await self._retriever.retrieve(
                EvidenceRequest(
                    dealer_group_id=request.dealer_group_id,
                    category=request.category,
                    # The concern is the only natural-language description of the
                    # problem. Without it a semantic retriever searches for the
                    # bare category slug, which matches by luck.
                    detected_need_hint=plan.concern,
                )
            )
        except EvidenceRetrievalError as exc:
            self._trace_failure(provider, model, started, f"EVIDENCE_{exc.code}")
            # `from None`, not `from exc`: Agent Framework records the formatted
            # traceback of an escaping exception on the executor and workflow
            # spans, and the chained cause can carry retrieved document text.
            # `safe_message` is already the caller-safe summary.
            raise StepFailed(
                self._run.state.failure(
                    status="evidence_missing",
                    error_code="EVIDENCE_MISSING",
                    error_message=exc.safe_message,
                )
            ) from None

        # An empty bundle is not a successful retrieval. Without this the run
        # spent two model calls and then failed validation as
        # "invalid_model_json", blaming the model for missing evidence.
        if bundle.is_empty():
            self._trace_failure(provider, model, started, "EVIDENCE_EMPTY")
            raise StepFailed(
                self._run.state.failure(
                    status="evidence_missing",
                    error_code="EVIDENCE_MISSING",
                    error_message="No dealer-group-scoped evidence was found for this request.",
                )
            )

        self._run.state.evidence_count = len(bundle.citations)
        self._run.step.trace_local(
            AgentTraceStep(
                agent="evidence-retrieval",
                status="ok",
                provider=provider,
                model=model,
                latency_ms=_elapsed_ms(started),
                token_estimate=None,
                citation_count=len(bundle.citations),
            )
        )
        await ctx.send_message(plan.with_(evidence=bundle))

    def _trace_failure(self, provider: str, model: str, started: float, code: str) -> None:
        self._run.step.trace_local(
            AgentTraceStep(
                agent="evidence-retrieval",
                status="evidence_missing",
                provider=provider,
                model=model,
                latency_ms=_elapsed_ms(started),
                token_estimate=None,
                issue_codes=[code],
                citation_count=0,
            )
        )


class Analyse(Executor):
    """Dealership indicators in, findings out. Outside the repair loop."""

    def __init__(self, run: PlanRun, agent: DataAnalystAgent) -> None:
        super().__init__(id="data-analyst")
        self._run = run
        self._agent = agent

    @handler
    async def analyse(self, plan: PlanState, ctx: WorkflowContext[PlanState]) -> None:
        request = self._run.request
        context = DataAnalystContext(
            dealer_group_id=request.dealer_group_id,
            dealership_label=request.dealership_label,
            region_id=request.region_id,
            segment=request.segment,
            process_score=request.process_score,
            appointment_attendance_rate=request.appointment_attendance_rate,
            followup_index=request.followup_index,
            engagement_index=request.engagement_index,
            area_series=request.area_series,
            operations_series=request.operations_series,
            category=request.category,
            concern_text=plan.concern,
        )
        analysis = await self._run.step.call(
            DATA_ANALYST_NAME,
            lambda: self._agent.analyze(context, deadline=self._run.state.deadline),
        )
        self._run.check_handoff(
            schema="data-analysis-result.schema.json",
            source="data-analyst-agent",
            target="support-recommendation-agent",
            payload=envelopes.analyst_payload(analysis),
            agent=DATA_ANALYST_NAME,
        )
        await ctx.send_message(plan.with_(analysis=analysis))


class Recommend(Executor):
    """Findings plus the allowed catalogs in, a draft plan out.

    The only node the repair edge points back at: a rejected draft is the
    recommender's problem, so re-running retrieval or analysis would spend a
    model call and change nothing.
    """

    def __init__(self, run: PlanRun, agent: SupportRecommendationAgent) -> None:
        super().__init__(id="support-recommender")
        self._run = run
        self._agent = agent

    @handler
    async def recommend(self, plan: PlanState, ctx: WorkflowContext[PlanState]) -> None:
        attempts = plan.attempts + 1
        repairing = attempts > 1
        # Named so the repair shows as its own row in the trace.
        agent_name = f"{RECOMMENDER_NAME}:repair" if repairing else RECOMMENDER_NAME
        guidance = (
            plan.report.repair_guidance[:MAX_REPAIR_GUIDANCE_CHARS]
            if repairing and plan.report is not None
            else ""
        )
        context = self._context(plan)

        result = await self._run.step.call(
            agent_name,
            lambda: self._agent.recommend_with_counts(
                plan.require_analysis(),
                context,
                repair_guidance=guidance,
                deadline=self._run.state.deadline,
            ),
        )
        # Unwrap immediately: `PlanState.with_` and `recommender_payload` are
        # untyped, so passing the wrapper on would fail silently.
        draft = result.draft
        self._run.check_handoff(
            schema="support-recommendation-result.schema.json",
            source="support-recommendation-agent",
            target="validator-agent",
            payload=envelopes.recommender_payload(draft),
            agent=agent_name,
        )
        # Recorded on every attempt, not only on success: a run that failed
        # validation used to audit zero citations, which read as ungrounded.
        self._run.state.citation_count = len(draft.citations)
        self._run.state.citations_proposed = result.citations_proposed
        self._run.state.citations_accepted = result.citations_accepted
        self._run.state.attempts = attempts
        await ctx.send_message(plan.with_(draft=draft, attempts=attempts))

    def _context(self, plan: PlanState) -> SupportRecommenderContext:
        request = self._run.request
        return SupportRecommenderContext(
            dealer_group_id=request.dealer_group_id,
            category=request.category,
            concern_text=plan.concern,
            allowed_resources=request.allowed_resources,
            allowed_goal_ids=request.allowed_goal_ids,
            allowed_strategy_ids=request.allowed_strategy_ids,
            evidence=plan.require_evidence(),
        )


class Validate(Executor):
    """Deterministic checks decide pass or fail; the model only advises."""

    def __init__(self, run: PlanRun, agent: ValidatorAgent) -> None:
        super().__init__(id="validator")
        self._run = run
        self._agent = agent

    @handler
    async def validate(self, plan: PlanState, ctx: WorkflowContext[PlanState]) -> None:
        draft = plan.require_draft()
        payload = ValidatorInput(
            analysis=plan.require_analysis(), draft=draft, context=self._context(plan)
        )
        # The advisory critique cannot change a verdict, so the recheck after
        # a repair does not pay for it a second time.
        use_llm_critique = plan.attempts == 1

        report = await self._run.step.call(
            VALIDATOR_NAME,
            lambda: self._agent.validate(
                payload,
                use_llm_critique=use_llm_critique,
                deadline=self._run.state.deadline,
            ),
            outcome=lambda r: StepOutcome(
                status="passed" if r.passed else "failed",
                issue_codes=list(r.issue_codes),
                warning_codes=list(r.warning_codes),
                citation_count=len(draft.citations),
            ),
        )
        self._run.check_handoff(
            schema="validation-result.schema.json",
            source="validator-agent",
            target="coordinator",
            payload=envelopes.validator_payload(report),
            agent=VALIDATOR_NAME,
        )
        # Set after the call returns, so a timeout inside the advisory
        # critique still counts as "the checks ran".
        self._run.state.validation_reached = True
        self._run.state.deterministic_checks_total = len(DETERMINISTIC_CHECKS)
        await ctx.send_message(plan.with_(report=report))

    def _context(self, plan: PlanState) -> ValidatorContext:
        request = self._run.request
        return ValidatorContext(
            dealer_group_id=request.dealer_group_id,
            allowed_resource_ids=tuple(r.id for r in request.allowed_resources),
            allowed_goal_ids=request.allowed_goal_ids,
            allowed_strategy_ids=request.allowed_strategy_ids,
            allowed_citation_ids=tuple(c.citation_id for c in plan.require_evidence().citations),
            required_contract_version=CONTRACT_VERSION,
        )


class Finalise(Executor):
    """Terminal node for an accepted draft."""

    def __init__(self, run: PlanRun, provider_display: str) -> None:
        super().__init__(id="finalise")
        self._run = run
        self._provider_display = provider_display

    @handler
    async def finalise(
        self, plan: PlanState, ctx: WorkflowContext[Never, CoordinatorResult]
    ) -> None:
        state = self._run.state
        report = plan.require_report()
        resources_proposed, resources_accepted, unknown_resource_ids = _resource_accounting(
            self._run, plan
        )
        await ctx.yield_output(
            CoordinatorResult(
                status="ok",
                error_code=None,
                error_message=None,
                recommendation=build_recommendation(
                    analysis=plan.require_analysis(),
                    draft=plan.require_draft(),
                    allowed=self._run.request.allowed_resources,
                    report=report,
                    provider_display=self._provider_display,
                ),
                agent_trace=state.trace,
                provider_model=state.provider_model,
                correlation_id=state.correlation_id,
                dealer_group_id=self._run.request.dealer_group_id,
                evidence_count=state.evidence_count,
                citation_count=state.citation_count,
                validator_status=report.safe_summary or "passed",
                citations_proposed=state.citations_proposed,
                citations_accepted=state.citations_accepted,
                resources_proposed=resources_proposed,
                resources_accepted=resources_accepted,
                unknown_resource_ids=unknown_resource_ids,
                attempts=state.attempts,
                validation_reached=state.validation_reached,
                deterministic_checks_total=state.deterministic_checks_total,
            )
        )


class Refuse(Executor):
    """Terminal node for a draft rejected twice. Returns no recommendation."""

    def __init__(self, run: PlanRun) -> None:
        super().__init__(id="refuse")
        self._run = run

    @handler
    async def refuse(self, plan: PlanState, ctx: WorkflowContext[Never, CoordinatorResult]) -> None:
        report = plan.require_report()
        proposed, accepted, unknown = _resource_accounting(self._run, plan)
        base = self._run.state.failure(
            status="validation_failed",
            error_code="VALIDATION_FAILED_AFTER_REPAIR",
            error_message=(
                "Recommendation could not be validated after one repair "
                "attempt. No recommendation is returned."
            ),
            validator_status=report.safe_summary or "failed",
        )
        # A refusal is the one outcome where an out-of-catalog resource id is
        # still visible: on the accepted path the validator has already
        # rejected any draft that carried one.
        await ctx.yield_output(
            replace(
                base,
                resources_proposed=proposed,
                resources_accepted=accepted,
                unknown_resource_ids=unknown,
            )
        )


def _resource_accounting(run: PlanRun, plan: PlanState) -> tuple[int, int, list[str]]:
    """How many referenced resource ids were in the request's allowed catalog."""

    allowed = {r.id for r in run.request.allowed_resources}
    proposed = list(dict.fromkeys(plan.require_draft().resource_ids))
    unknown = [rid for rid in proposed if rid not in allowed]
    return len(proposed), len(proposed) - len(unknown), unknown


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
