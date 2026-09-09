"""Agent Coordinator - orchestrates the three-agent workflow.

The coordinator is deterministic Python. It:

- generates a `correlation_id` per request,
- retrieves district-scoped evidence from `evidence.EvidenceRetriever`,
- passes `district_id`, `correlation_id`, and citations through every
  inter-agent hop,
- validates each hop's message against a versioned JSON Schema,
- enforces per-run and total budgets,
- runs at most one repair pass on the recommender,
- classifies typed provider failures into a stable API status taxonomy.

Nothing here talks to a language model directly.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import ValidationError

from ..agents.data_analyst import DataAnalystAgent, DataAnalystContext
from ..agents.data_analyst.agent import AGENT_NAME as DATA_ANALYST_NAME
from ..agents.shared.contracts import (
    CONTRACT_VERSION,
    Citation,
    DataAnalystOutput,
    ResourceRef,
    SupportRecommendationDraft,
    ValidatorReport,
)
from ..agents.shared.sanitization import sanitize_free_text
from ..agents.support_recommender import (
    SupportRecommendationAgent,
    SupportRecommenderContext,
)
from ..agents.support_recommender.agent import AGENT_NAME as RECOMMENDER_NAME
from ..agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput
from ..agents.validator.agent import AGENT_NAME as VALIDATOR_NAME
from ..config import (
    CONCERN_TEXT_MAX_LEN,
    ORCHESTRATION_TOTAL_BUDGET_SECONDS,
)
from ..contracts_registry import ContractsRegistry, ContractValidationError
from ..evidence import (
    EvidenceRequest,
    EvidenceRetrievalError,
    EvidenceRetriever,
)
from ..foundry_agents.errors import (
    AuthError,
    ConfigurationError,
    ContentFilterError,
    FoundryProviderError,
    FoundryRunError,
    FoundryTimeoutError,
    RequiresActionError,
    ThrottledError,
)
from ..foundry_agents.maf_runtime import (
    PROVIDER_ID,
    CallMetrics,
    MafAgentRuntime,
    collect_call_metrics,
)
from ..human_review import HumanReviewState
from ..models import AgentTraceStep, Recommendation, RecommendationCitation, RecommendationResource
from ..telemetry import TelemetryRecorder


@dataclass(frozen=True)
class CoordinatorRequest:
    district_id: str
    learner_label: str
    grade: int
    school_id: str
    group: str
    proficiency_index: float
    attendance_rate: float
    behavior_index: float
    engagement_index: float
    assessment_count: int
    behavior_record_count: int
    category: str
    concern_text: str
    allowed_resources: tuple[ResourceRef, ...]
    allowed_smart_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoordinatorResult:
    status: str
    error_code: str | None
    error_message: str | None
    recommendation: Recommendation | None
    agent_trace: list[AgentTraceStep]
    provider_model: str
    correlation_id: str
    district_id: str
    evidence_count: int = 0
    citation_count: int = 0
    validator_status: str = ""


_T = TypeVar("_T")

# Recorded on trace steps that completed without any model call, so a
# deterministic step is never credited to a model that did no work.
LOCAL_STEP_MODEL = "none"


PROVIDER_ERROR_TO_STATUS: dict[type[FoundryProviderError], tuple[str, str]] = {
    ConfigurationError: ("provider_missing", "AGENT_PROVIDER_MISSING"),
    AuthError: ("provider_error", "AGENT_PROVIDER_AUTH_DENIED"),
    ThrottledError: ("provider_throttling", "AGENT_PROVIDER_THROTTLING"),
    ContentFilterError: ("provider_content_filter", "AGENT_PROVIDER_CONTENT_FILTER"),
    FoundryTimeoutError: ("provider_timeout", "AGENT_PROVIDER_TIMEOUT"),
    RequiresActionError: ("provider_error", "AGENT_PROVIDER_REQUIRES_ACTION"),
    FoundryRunError: ("provider_error", "AGENT_PROVIDER_ERROR"),
}


@dataclass
class _RunState:
    """Mutable per-request state passed to helpers."""

    correlation_id: str
    district_id: str
    provider_model: str
    trace: list[AgentTraceStep] = field(default_factory=list)
    calls: list[CallMetrics] = field(default_factory=list)

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


class AgentCoordinator:
    def __init__(
        self,
        *,
        runtime: MafAgentRuntime,
        telemetry: TelemetryRecorder,
        contracts: ContractsRegistry,
        evidence_retriever: EvidenceRetriever,
        provider_display: str,
    ) -> None:
        self._runtime = runtime
        self._telemetry = telemetry
        self._contracts = contracts
        self._evidence = evidence_retriever
        self._provider_display = provider_display
        self._data_analyst = DataAnalystAgent(runtime)
        self._recommender = SupportRecommendationAgent(runtime)
        self._validator = ValidatorAgent(runtime)

    async def run(self, request: CoordinatorRequest) -> CoordinatorResult:
        with collect_call_metrics() as calls:
            return await self._run(request, calls)

    async def _run(
        self, request: CoordinatorRequest, calls: list[CallMetrics]
    ) -> CoordinatorResult:
        correlation_id = str(uuid.uuid4())
        deadline = time.monotonic() + ORCHESTRATION_TOTAL_BUDGET_SECONDS
        state = _RunState(
            correlation_id=correlation_id,
            district_id=request.district_id,
            provider_model=self._provider_display,
            calls=calls,
        )

        sanitized_concern = sanitize_free_text(request.concern_text, max_len=CONCERN_TEXT_MAX_LEN)

        # 1) District-scoped evidence retrieval BEFORE any agent call.
        # The provider and latency are read off the retriever rather than
        # hardcoded, so the trace distinguishes fixture runs from grounded ones.
        evidence_provider = getattr(self._evidence, "provider_name", "unknown")
        evidence_model = getattr(self._evidence, "provider_model", "unknown")
        evidence_started = time.monotonic()
        try:
            evidence = await self._evidence.retrieve(
                EvidenceRequest(
                    district_id=request.district_id,
                    category=request.category,
                    detected_need_hint="",
                )
            )
        except EvidenceRetrievalError as exc:
            state.trace.append(
                AgentTraceStep(
                    agent="evidence-retrieval",
                    status="evidence_missing",
                    provider=evidence_provider,
                    model=evidence_model,
                    latency_ms=int((time.monotonic() - evidence_started) * 1000),
                    token_estimate=None,
                    issue_codes=[f"EVIDENCE_{exc.code}"],
                )
            )
            self._telemetry.record(
                "evidence_retrieval",
                {
                    "correlation_id": correlation_id,
                    "district_id": request.district_id,
                    "status": "error",
                    "code": exc.code,
                },
            )
            return self._finalize_failure(
                state,
                status="evidence_missing",
                error_code="EVIDENCE_MISSING",
                error_message=exc.safe_message,
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )

        # An empty bundle is not a successful retrieval. Without this guard the
        # run continued, spent two model calls, and then failed at recommender
        # validation as "invalid_model_json" - blaming the model for missing
        # evidence. `EvidenceBundle.is_empty()` existed for this and had no
        # callers.
        if evidence.is_empty():
            state.trace.append(
                AgentTraceStep(
                    agent="evidence-retrieval",
                    status="evidence_missing",
                    provider=evidence_provider,
                    model=evidence_model,
                    latency_ms=int((time.monotonic() - evidence_started) * 1000),
                    token_estimate=None,
                    issue_codes=["EVIDENCE_EMPTY"],
                    citation_count=0,
                )
            )
            self._telemetry.record(
                "evidence_retrieval",
                {
                    "correlation_id": correlation_id,
                    "district_id": request.district_id,
                    "status": "empty",
                    "citation_count": 0,
                },
            )
            return self._finalize_failure(
                state,
                status="evidence_missing",
                error_code="EVIDENCE_MISSING",
                error_message="No district-scoped evidence was found for this request.",
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )

        state.trace.append(
            AgentTraceStep(
                agent="evidence-retrieval",
                status="ok",
                provider=evidence_provider,
                model=evidence_model,
                latency_ms=int((time.monotonic() - evidence_started) * 1000),
                token_estimate=None,
                citation_count=len(evidence.citations),
            )
        )
        self._telemetry.record(
            "evidence_retrieval",
            {
                "correlation_id": correlation_id,
                "district_id": request.district_id,
                "status": "ok",
                "citation_count": len(evidence.citations),
            },
        )

        # 2) Data Analyst
        analyst_ctx = DataAnalystContext(
            district_id=request.district_id,
            learner_label=request.learner_label,
            grade=request.grade,
            school_id=request.school_id,
            group=request.group,
            proficiency_index=request.proficiency_index,
            attendance_rate=request.attendance_rate,
            behavior_index=request.behavior_index,
            engagement_index=request.engagement_index,
            assessment_count=request.assessment_count,
            behavior_record_count=request.behavior_record_count,
            category=request.category,
            sanitized_concern_text=sanitized_concern,
        )
        analysis_result = await self._call(
            DATA_ANALYST_NAME,
            lambda: self._data_analyst.analyze(analyst_ctx, deadline=deadline),
            state=state,
            deadline=deadline,
        )
        if isinstance(analysis_result, CoordinatorResult):
            return analysis_result

        maybe_fail = self._protocol_validate(
            schema_name="data-analysis-result.schema.json",
            envelope=self._envelope(
                source_agent="data-analyst-agent",
                target_agent="support-recommendation-agent",
                payload=self._analyst_payload(analysis_result),
                correlation_id=correlation_id,
            ),
            state=state,
            agent_name=DATA_ANALYST_NAME,
        )
        if maybe_fail is not None:
            return maybe_fail

        # 3) Support Recommendation (with district-scoped evidence bundle)
        rec_ctx = SupportRecommenderContext(
            district_id=request.district_id,
            category=request.category,
            sanitized_concern_text=sanitized_concern,
            allowed_resources=request.allowed_resources,
            allowed_smart_goal_ids=request.allowed_smart_goal_ids,
            allowed_strategy_ids=request.allowed_strategy_ids,
            evidence=evidence,
        )
        draft_result = await self._call(
            RECOMMENDER_NAME,
            lambda: self._recommender.recommend(
                analysis_result, rec_ctx, repair_guidance="", deadline=deadline
            ),
            state=state,
            deadline=deadline,
        )
        if isinstance(draft_result, CoordinatorResult):
            return draft_result

        maybe_fail = self._protocol_validate(
            schema_name="support-recommendation-result.schema.json",
            envelope=self._envelope(
                source_agent="support-recommendation-agent",
                target_agent="validator-agent",
                payload=self._recommender_payload(draft_result),
                correlation_id=correlation_id,
            ),
            state=state,
            agent_name=RECOMMENDER_NAME,
        )
        if maybe_fail is not None:
            return maybe_fail

        # 4) Validator
        validator_ctx = ValidatorContext(
            district_id=request.district_id,
            allowed_resource_ids=tuple(r.id for r in request.allowed_resources),
            allowed_smart_goal_ids=request.allowed_smart_goal_ids,
            allowed_strategy_ids=request.allowed_strategy_ids,
            allowed_citation_ids=tuple(c.citation_id for c in evidence.citations),
            required_contract_version=CONTRACT_VERSION,
        )
        report = await self._validate(analysis_result, draft_result, validator_ctx, state, deadline)
        if isinstance(report, CoordinatorResult):
            return report

        maybe_fail = self._protocol_validate(
            schema_name="validation-result.schema.json",
            envelope=self._envelope(
                source_agent="validator-agent",
                target_agent="coordinator",
                payload=self._validator_payload(report),
                correlation_id=correlation_id,
            ),
            state=state,
            agent_name=VALIDATOR_NAME,
        )
        if maybe_fail is not None:
            return maybe_fail

        # 5) Optional one-shot repair
        if not report.passed:
            repair_guidance = _sanitize_repair(report.repair_guidance)
            repair_result = await self._call(
                RECOMMENDER_NAME + ":repair",
                lambda: self._recommender.recommend(
                    analysis_result, rec_ctx, repair_guidance=repair_guidance, deadline=deadline
                ),
                state=state,
                deadline=deadline,
            )
            if isinstance(repair_result, CoordinatorResult):
                return repair_result
            draft_result = repair_result

            maybe_fail = self._protocol_validate(
                schema_name="support-recommendation-result.schema.json",
                envelope=self._envelope(
                    source_agent="support-recommendation-agent",
                    target_agent="validator-agent",
                    payload=self._recommender_payload(draft_result),
                    correlation_id=correlation_id,
                ),
                state=state,
                agent_name=RECOMMENDER_NAME + ":repair",
            )
            if maybe_fail is not None:
                return maybe_fail

            report = await self._validate(
                analysis_result,
                draft_result,
                validator_ctx,
                state,
                deadline,
                use_llm_critique=False,
            )
            if isinstance(report, CoordinatorResult):
                return report

            maybe_fail = self._protocol_validate(
                schema_name="validation-result.schema.json",
                envelope=self._envelope(
                    source_agent="validator-agent",
                    target_agent="coordinator",
                    payload=self._validator_payload(report),
                    correlation_id=correlation_id,
                ),
                state=state,
                agent_name=VALIDATOR_NAME,
            )
            if maybe_fail is not None:
                return maybe_fail

            if not report.passed:
                return self._finalize_failure(
                    state,
                    status="validation_failed",
                    error_code="VALIDATION_FAILED_AFTER_REPAIR",
                    error_message=(
                        "Recommendation could not be validated after one repair "
                        "attempt. No recommendation is returned."
                    ),
                    evidence_count=len(evidence.citations),
                    citation_count=len(draft_result.citations),
                    validator_status=report.safe_summary or "failed",
                )

        recommendation = _build_recommendation(
            analysis=analysis_result,
            draft=draft_result,
            allowed=request.allowed_resources,
            report=report,
            provider_display=self._provider_display,
        )
        return CoordinatorResult(
            status="ok",
            error_code=None,
            error_message=None,
            recommendation=recommendation,
            agent_trace=state.trace,
            provider_model=state.provider_model,
            correlation_id=correlation_id,
            district_id=request.district_id,
            evidence_count=len(evidence.citations),
            citation_count=len(draft_result.citations),
            validator_status=report.safe_summary or "passed",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _finalize_failure(
        self,
        state: _RunState,
        *,
        status: str,
        error_code: str,
        error_message: str,
        evidence_count: int,
        citation_count: int,
        validator_status: str,
    ) -> CoordinatorResult:
        return CoordinatorResult(
            status=status,
            error_code=error_code,
            error_message=error_message,
            recommendation=None,
            agent_trace=state.trace,
            provider_model=state.provider_model,
            correlation_id=state.correlation_id,
            district_id=state.district_id,
            evidence_count=evidence_count,
            citation_count=citation_count,
            validator_status=validator_status,
        )

    def _envelope(
        self,
        *,
        source_agent: str,
        target_agent: str | None,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        env: dict[str, Any] = {
            "schema_version": "1.0.0",
            "message_id": str(uuid.uuid4()),
            "trace_id": correlation_id,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_agent": source_agent,
            "payload": payload,
        }
        if target_agent is not None:
            env["target_agent"] = target_agent
        return env

    def _protocol_validate(
        self,
        *,
        schema_name: str,
        envelope: dict[str, Any],
        state: _RunState,
        agent_name: str,
    ) -> CoordinatorResult | None:
        try:
            self._contracts.validate(schema_name, envelope)
        except ContractValidationError as exc:
            state.trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status="failed",
                    provider=PROVIDER_ID,
                    model=state.provider_model,
                    latency_ms=0,
                    token_estimate=None,
                    issue_codes=["PROTOCOL_VALIDATION_FAILED"],
                )
            )
            return self._finalize_failure(
                state,
                status="invalid_model_json",
                error_code="PROTOCOL_VALIDATION_FAILED",
                error_message=(
                    f"Message failed protocol validation ({schema_name}: {exc.safe_reason})."
                ),
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )
        return None

    @staticmethod
    def _analyst_payload(analysis: DataAnalystOutput) -> dict[str, Any]:
        return {
            "district_id": analysis.district_id,
            **analysis.analysis.model_dump(),
            "citations": [c.model_dump(mode="json") for c in analysis.citations],
            "synthetic_only": True,
        }

    @staticmethod
    def _recommender_payload(draft: SupportRecommendationDraft) -> dict[str, Any]:
        return {
            "district_id": draft.district_id,
            "detected_need": draft.detected_need,
            "support_tier": draft.support_tier,
            "recommended_frequency": draft.recommended_frequency,
            "grouping_guidance": draft.grouping_guidance,
            "resource_ids": list(draft.resource_ids),
            "rationale": draft.rationale,
            "smart_goal_suggestions": list(draft.smart_goal_suggestions),
            "strategy_suggestions": list(draft.strategy_suggestions),
            "educator_next_steps": list(draft.educator_next_steps),
            "progress_monitoring": list(draft.progress_monitoring),
            "review_window_days": draft.review_window_days,
            "decision_rule": draft.decision_rule,
            "caveats": list(draft.caveats),
            "citations": [c.model_dump(mode="json") for c in draft.citations],
            "synthetic_only": True,
        }

    @staticmethod
    def _validator_payload(report: ValidatorReport) -> dict[str, Any]:
        return {
            "district_id": report.district_id,
            "passed": report.passed,
            "issue_codes": list(report.issue_codes),
            "warning_codes": list(report.warning_codes),
            "failed_fields": list(report.failed_fields),
            "safe_summary": report.safe_summary,
            "repair_guidance": report.repair_guidance,
            "synthetic_only": True,
        }

    async def _call(
        self,
        agent_name: str,
        fn: Callable[[], Awaitable[_T]],
        *,
        state: _RunState,
        deadline: float,
    ) -> _T | CoordinatorResult:
        if time.monotonic() >= deadline:
            state.trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status="budget_exhausted",
                    provider=PROVIDER_ID,
                    model=state.provider_model,
                    latency_ms=0,
                    token_estimate=None,
                    issue_codes=["ORCHESTRATION_BUDGET_EXHAUSTED"],
                )
            )
            return self._finalize_failure(
                state,
                status="orchestration_budget_exhausted",
                error_code="ORCHESTRATION_BUDGET_EXHAUSTED",
                error_message="Orchestration exceeded total budget.",
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )
        started = time.monotonic()
        calls_before = len(state.calls)
        try:
            result = await fn()
        except FoundryProviderError as exc:
            latency = int((time.monotonic() - started) * 1000)
            status, code = _classify_provider_error(exc)
            state.trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status=status,
                    provider=PROVIDER_ID,
                    model=state.provider_model,
                    latency_ms=latency,
                    token_estimate=None,
                    issue_codes=[code],
                )
            )
            self._telemetry.record(
                "agent_call",
                {
                    "correlation_id": state.correlation_id,
                    "district_id": state.district_id,
                    "agent": agent_name,
                    "status": status,
                    "latency_ms": latency,
                },
            )
            return self._finalize_failure(
                state,
                status=status,
                error_code=code,
                error_message=_safe_message(status),
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )
        except ValueError as exc:
            latency = int((time.monotonic() - started) * 1000)
            # Never put exception text in an issue code. Pydantic quotes the
            # offending value, which is model output derived from a district's
            # evidence, and issue codes travel to the response and telemetry.
            code = _invalid_json_code(exc)
            state.trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status="invalid_model_json",
                    provider=PROVIDER_ID,
                    model=state.provider_model,
                    latency_ms=latency,
                    token_estimate=None,
                    issue_codes=[code],
                )
            )
            return self._finalize_failure(
                state,
                status="invalid_model_json",
                error_code="AGENT_INVALID_JSON",
                error_message="Remote agent returned invalid or off-schema JSON.",
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )
        latency = int((time.monotonic() - started) * 1000)
        served_model, tokens = state.drain_calls(calls_before)
        state.trace.append(
            AgentTraceStep(
                agent=agent_name,
                status="ok",
                provider=PROVIDER_ID,
                model=served_model or LOCAL_STEP_MODEL,
                latency_ms=latency,
                token_estimate=tokens,
            )
        )
        self._telemetry.record(
            "agent_call",
            {
                "correlation_id": state.correlation_id,
                "district_id": state.district_id,
                "agent": agent_name,
                "status": "ok",
                "latency_ms": latency,
                "model": served_model,
            },
        )
        return result

    async def _validate(
        self,
        analysis: DataAnalystOutput,
        draft: SupportRecommendationDraft,
        ctx: ValidatorContext,
        state: _RunState,
        deadline: float,
        *,
        use_llm_critique: bool = True,
    ) -> ValidatorReport | CoordinatorResult:
        if time.monotonic() >= deadline:
            state.trace.append(
                AgentTraceStep(
                    agent=VALIDATOR_NAME,
                    status="budget_exhausted",
                    provider=PROVIDER_ID,
                    model=state.provider_model,
                    latency_ms=0,
                    token_estimate=None,
                    issue_codes=["ORCHESTRATION_BUDGET_EXHAUSTED"],
                )
            )
            return self._finalize_failure(
                state,
                status="orchestration_budget_exhausted",
                error_code="ORCHESTRATION_BUDGET_EXHAUSTED",
                error_message="Orchestration exceeded total budget.",
                evidence_count=0,
                citation_count=0,
                validator_status="",
            )
        started = time.monotonic()
        calls_before = len(state.calls)
        report = await self._validator.validate(
            ValidatorInput(analysis=analysis, draft=draft, context=ctx),
            use_llm_critique=use_llm_critique,
            deadline=deadline,
        )
        latency = int((time.monotonic() - started) * 1000)
        served_model, tokens = state.drain_calls(calls_before)
        state.trace.append(
            AgentTraceStep(
                agent=VALIDATOR_NAME,
                status="passed" if report.passed else "failed",
                provider=PROVIDER_ID,
                # Deterministic validation makes no model call, so naming a
                # model here would misattribute work that never happened.
                model=served_model or LOCAL_STEP_MODEL,
                latency_ms=latency,
                token_estimate=tokens,
                issue_codes=list(report.issue_codes),
                warning_codes=list(report.warning_codes),
                citation_count=len(draft.citations),
            )
        )
        # The validator runs outside `_call`, so without this it appeared in
        # the response trace but never in telemetry - and Module 9's
        # per-agent latency query silently omitted the one step that decides
        # whether an answer ships.
        self._telemetry.record(
            "agent_call",
            {
                "correlation_id": state.correlation_id,
                "district_id": state.district_id,
                "agent": VALIDATOR_NAME,
                "status": "passed" if report.passed else "failed",
                "latency_ms": latency,
                "model": served_model or LOCAL_STEP_MODEL,
                "citation_count": len(draft.citations),
            },
        )
        return report


def _classify_provider_error(exc: FoundryProviderError) -> tuple[str, str]:
    for cls, mapping in PROVIDER_ERROR_TO_STATUS.items():
        if isinstance(exc, cls):
            return mapping
    return ("provider_error", "AGENT_PROVIDER_ERROR")


_SAFE_MESSAGES = {
    "provider_timeout": "Remote agent run timed out.",
    "provider_throttling": "Remote agent was throttled.",
    "provider_content_filter": "Remote agent blocked the request via content safety.",
    "provider_error": "Remote agent returned an error.",
    "provider_missing": (
        "Foundry Agent Service is not configured or bindings are missing. "
        "Run scripts/validate_agent_definitions.py."
    ),
    "evidence_missing": (
        "District-scoped evidence was not available. Confirm the district_id and "
        "the fixture retriever for this environment."
    ),
}


def _safe_message(status: str) -> str:
    return _SAFE_MESSAGES.get(status, "Unknown remote agent error.")


# Bounded set. An issue code reaches the API response and telemetry, so it
# must never be built from exception text. The trace contract restricts codes
# to ^[A-Z][A-Z0-9_]{3,59}$, so no colons or lowercase.
_INVALID_JSON_SCHEMA = "AGENT_INVALID_JSON_SCHEMA_MISMATCH"
_INVALID_JSON_DECODE = "AGENT_INVALID_JSON_NOT_JSON"
_INVALID_JSON_OTHER = "AGENT_INVALID_JSON_UNPARSEABLE"


def _invalid_json_code(exc: Exception) -> str:
    """Classify a parse failure without echoing its message."""

    if isinstance(exc, json.JSONDecodeError):
        return _INVALID_JSON_DECODE
    if isinstance(exc, ValidationError):
        return _INVALID_JSON_SCHEMA
    return _INVALID_JSON_OTHER


def _sanitize_repair(text: str) -> str:
    return text[:800]


def _to_recommendation_citation(c: Citation) -> RecommendationCitation:
    return RecommendationCitation(
        citation_id=c.citation_id,
        district_id=c.district_id,
        source_type=c.source_type.value,
        source_title=c.source_title,
        section_or_page=c.section_or_page,
        evidence_summary=c.evidence_summary,
        source_ref=c.source_ref,
        retrieved_at=c.retrieved_at,
        confidence=c.confidence,
    )


def _build_recommendation(
    *,
    analysis: DataAnalystOutput,
    draft: SupportRecommendationDraft,
    allowed: tuple[ResourceRef, ...],
    report: ValidatorReport,
    provider_display: str,
) -> Recommendation:
    by_id = {r.id: r for r in allowed}
    resource_matches = [
        RecommendationResource(id=r.id, label=r.label, kind=r.kind)
        for r in (by_id[rid] for rid in draft.resource_ids if rid in by_id)
    ]
    generated_by = f"Generated by three collaborating agents via {provider_display}."
    return Recommendation(
        district_id=draft.district_id,
        detected_need=analysis.analysis.detected_need or draft.detected_need,
        evidence_summary=list(analysis.analysis.evidence_bullets),
        rationale=draft.rationale,
        support_tier=draft.support_tier,
        recommended_frequency=draft.recommended_frequency,
        grouping_guidance=draft.grouping_guidance,
        resource_matches=resource_matches,
        educator_next_steps=list(draft.educator_next_steps),
        progress_monitoring=list(draft.progress_monitoring),
        review_window_days=draft.review_window_days,
        decision_rule=draft.decision_rule,
        caveats=list(draft.caveats),
        smart_goal_suggestions=list(draft.smart_goal_suggestions),
        strategy_suggestions=list(draft.strategy_suggestions),
        citations=[_to_recommendation_citation(c) for c in draft.citations],
        completeness={
            "ok": report.passed,
            "missing": list(report.issue_codes),
        },
        human_review_state=HumanReviewState.PENDING_REVIEW.value,
        generated_by=generated_by,
    )
