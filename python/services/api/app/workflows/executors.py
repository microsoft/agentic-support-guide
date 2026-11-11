"""The six nodes of the plan workflow.

One class per node. Each one is thin: take the `PlanState` off the edge, do
one job, report its trace row with `ctx.yield_output`, send the next
`PlanState`. `graph.py` wires them together.

The four working nodes are the graph's *intermediate* outputs, so their trace
rows reach the caller on the workflow's own event stream; only `Finalise` and
`Refuse` produce the run's result. Every node gets the same `PlanRun` -- the
request and the run's identity. Built fresh per request, because a `Workflow`
instance refuses concurrent runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Never, NoReturn

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
from ..foundry_agents.errors import FoundryProviderError
from ..foundry_agents.maf_runtime import PROVIDER_ID, RoleResponse
from .assembly import build_recommendation
from .failures import classify_provider_error, invalid_json_code, safe_message
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

MAX_REPAIR_GUIDANCE_CHARS = 800


@dataclass(frozen=True)
class PlanRun:
    """Everything a node needs that is not on the edge."""

    request: CoordinatorRequest
    context: RunContext


def _model_of(call: RoleResponse | None) -> str:
    return call.model if call is not None and call.model else LOCAL_STEP_MODEL


def _tokens_of(call: RoleResponse | None) -> int | None:
    return call.total_tokens if call is not None else None


async def _fail(
    ctx: WorkflowContext[PlanState, StepRecord],
    plan: PlanState,
    record: StepRecord,
    *,
    status: str,
    error_code: str,
    error_message: str,
) -> NoReturn:
    """Report the failed row, then stop the run."""

    await ctx.yield_output(record)
    # `from None` is a privacy control, not style. Agent Framework records
    # the escaping exception on the executor and workflow spans, and a
    # formatted traceback includes the chained cause -- for a Pydantic
    # failure that is `input_value=<model output>`. Breaking the chain
    # keeps the span to the typed code.
    raise StepFailed(
        status=status, error_code=error_code, error_message=error_message, plan=plan
    ) from None


async def _call_agent[T](
    ctx: WorkflowContext[PlanState, StepRecord],
    run: PlanRun,
    plan: PlanState,
    agent_name: str,
    invoke: Callable[[], Awaitable[T]],
) -> T:
    """Invoke one agent, or report the failure and stop the run."""

    try:
        return await invoke()
    except FoundryProviderError as exc:
        status, code = classify_provider_error(exc)
        await _fail(
            ctx,
            plan,
            StepRecord(
                agent=agent_name,
                status=status,
                provider=PROVIDER_ID,
                model=run.context.provider_model,
                issue_codes=(code,),
            ),
            status=status,
            error_code=code,
            error_message=safe_message(status),
        )
    except ValueError as exc:
        # Never put exception text in an issue code. Pydantic quotes the
        # offending value, which is model output derived from a dealer
        # group's evidence, and issue codes travel to the response.
        await _fail(
            ctx,
            plan,
            StepRecord(
                agent=agent_name,
                status="invalid_model_json",
                provider=PROVIDER_ID,
                model=run.context.provider_model,
                issue_codes=(invalid_json_code(exc),),
            ),
            status="invalid_model_json",
            error_code="AGENT_INVALID_JSON",
            error_message="Remote agent returned invalid or off-schema JSON.",
        )


class RetrieveEvidence(Executor):
    """Grounding, before any model call. An empty bundle stops the run."""

    def __init__(self, run: PlanRun, retriever: EvidenceRetriever) -> None:
        super().__init__(id="retrieve-evidence")
        self._run = run
        self._retriever = retriever

    @handler
    async def retrieve(self, plan: PlanState, ctx: WorkflowContext[PlanState, StepRecord]) -> None:
        provider = getattr(self._retriever, "provider_name", "unknown")
        model = getattr(self._retriever, "provider_model", "unknown")
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
            # `_fail` raises `from None`: Agent Framework records the formatted
            # traceback of an escaping exception on the executor and workflow
            # spans, and the chained cause can carry retrieved document text.
            # `safe_message` is already the caller-safe summary.
            await _fail(
                ctx,
                plan,
                _evidence_failure(provider, model, f"EVIDENCE_{exc.code}"),
                status="evidence_missing",
                error_code="EVIDENCE_MISSING",
                error_message=exc.safe_message,
            )

        # An empty bundle is not a successful retrieval. Without this the run
        # spent two model calls and then failed validation as
        # "invalid_model_json", blaming the model for missing evidence.
        if bundle.is_empty():
            await _fail(
                ctx,
                plan,
                _evidence_failure(provider, model, "EVIDENCE_EMPTY"),
                status="evidence_missing",
                error_code="EVIDENCE_MISSING",
                error_message="No dealer-group-scoped evidence was found for this request.",
            )

        await ctx.yield_output(
            StepRecord(
                agent="evidence-retrieval",
                status="ok",
                provider=provider,
                model=model,
                citation_count=len(bundle.citations),
            )
        )
        await ctx.send_message(plan.with_(evidence=bundle, evidence_count=len(bundle.citations)))


def _evidence_failure(provider: str, model: str, code: str) -> StepRecord:
    return StepRecord(
        agent="evidence-retrieval",
        status="evidence_missing",
        provider=provider,
        model=model,
        issue_codes=(code,),
    )


class Analyse(Executor):
    """Dealership indicators in, findings out. Outside the repair loop."""

    def __init__(self, run: PlanRun, agent: DataAnalystAgent) -> None:
        super().__init__(id="data-analyst")
        self._run = run
        self._agent = agent

    @handler
    async def analyse(self, plan: PlanState, ctx: WorkflowContext[PlanState, StepRecord]) -> None:
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
        result = await _call_agent(
            ctx, self._run, plan, DATA_ANALYST_NAME, lambda: self._agent.analyze_with_call(context)
        )
        await ctx.yield_output(
            StepRecord(
                agent=DATA_ANALYST_NAME,
                status="ok",
                provider=PROVIDER_ID,
                model=_model_of(result.call),
                token_estimate=_tokens_of(result.call),
            )
        )
        await ctx.send_message(plan.with_(analysis=result.output))


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
    async def recommend(self, plan: PlanState, ctx: WorkflowContext[PlanState, StepRecord]) -> None:
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

        result = await _call_agent(
            ctx,
            self._run,
            plan,
            agent_name,
            lambda: self._agent.recommend_with_counts(
                plan.require_analysis(), context, repair_guidance=guidance
            ),
        )
        await ctx.yield_output(
            StepRecord(
                agent=agent_name,
                status="ok",
                provider=PROVIDER_ID,
                model=_model_of(result.call),
                token_estimate=_tokens_of(result.call),
            )
        )
        # Recorded on every attempt, not only on success: a run that failed
        # validation used to audit zero citations, which read as ungrounded.
        await ctx.send_message(
            plan.with_(
                draft=result.draft,
                attempts=attempts,
                citation_count=len(result.draft.citations),
                citations_proposed=result.citations_proposed,
                citations_accepted=result.citations_accepted,
            )
        )

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
    async def validate(self, plan: PlanState, ctx: WorkflowContext[PlanState, StepRecord]) -> None:
        draft = plan.require_draft()
        payload = ValidatorInput(
            analysis=plan.require_analysis(), draft=draft, context=self._context(plan)
        )
        # The advisory critique cannot change a verdict, so the recheck after
        # a repair does not pay for it a second time.
        use_llm_critique = plan.attempts == 1

        result = await _call_agent(
            ctx,
            self._run,
            plan,
            VALIDATOR_NAME,
            lambda: self._agent.validate_with_call(payload, use_llm_critique=use_llm_critique),
        )
        report = result.report
        await ctx.yield_output(
            StepRecord(
                agent=VALIDATOR_NAME,
                status="passed" if report.passed else "failed",
                provider=PROVIDER_ID,
                model=_model_of(result.call),
                token_estimate=_tokens_of(result.call),
                issue_codes=tuple(report.issue_codes),
                warning_codes=tuple(report.warning_codes),
                citation_count=len(draft.citations),
            )
        )
        await ctx.send_message(
            plan.with_(
                report=report,
                validation_reached=True,
                deterministic_checks_total=len(DETERMINISTIC_CHECKS),
            )
        )

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
        context = self._run.context
        report = plan.require_report()
        resources_proposed, resources_accepted, unknown_resource_ids = _resource_accounting(
            self._run, plan
        )
        # The trace is the workflow's event stream, so the coordinator fills it in.
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
                agent_trace=[],
                provider_model=context.provider_model,
                correlation_id=context.correlation_id,
                dealer_group_id=self._run.request.dealer_group_id,
                evidence_count=plan.evidence_count,
                citation_count=plan.citation_count,
                validator_status=report.safe_summary or "passed",
                citations_proposed=plan.citations_proposed,
                citations_accepted=plan.citations_accepted,
                resources_proposed=resources_proposed,
                resources_accepted=resources_accepted,
                unknown_resource_ids=unknown_resource_ids,
                attempts=plan.attempts or None,
                validation_reached=plan.validation_reached,
                deterministic_checks_total=plan.deterministic_checks_total,
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
        base = failure_result(
            self._run.context,
            plan,
            [],
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
