"""Agent Coordinator - orchestrates the three-agent workflow.

The coordinator is deterministic orchestration, not a fourth agent. It
does not talk to a base model directly. Every LLM call goes through
FoundryRemoteAgentAdapter, which invokes a remote Azure AI Foundry
Agent Service assistant.

Sequence: sanitize -> Data Analyst -> protocol validate -> Support
Recommender -> protocol validate -> Validator -> optional single repair
of the recommender -> re-validate -> return.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from ..agents.data_analyst import DataAnalystAgent, DataAnalystContext
from ..agents.data_analyst.agent import AGENT_NAME as DATA_ANALYST_NAME
from ..agents.shared.contracts import (
    CONTRACT_VERSION,
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
from ..foundry_agents import (
    AuthError,
    ConfigurationError,
    ContentFilterError,
    FoundryProviderError,
    FoundryRemoteAgentAdapter,
    FoundryRunError,
    FoundryTimeoutError,
    RequiresActionError,
    ThrottledError,
)
from ..models import AgentTraceStep, Recommendation, RecommendationResource
from ..telemetry import TelemetryRecorder


@dataclass(frozen=True)
class CoordinatorRequest:
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


_T = TypeVar("_T")


PROVIDER_ERROR_TO_STATUS: dict[type[FoundryProviderError], tuple[str, str]] = {
    ConfigurationError: ("provider_missing", "AGENT_PROVIDER_MISSING"),
    AuthError: ("provider_error", "AGENT_PROVIDER_AUTH_DENIED"),
    ThrottledError: ("provider_throttling", "AGENT_PROVIDER_THROTTLING"),
    ContentFilterError: ("provider_content_filter", "AGENT_PROVIDER_CONTENT_FILTER"),
    FoundryTimeoutError: ("provider_timeout", "AGENT_PROVIDER_TIMEOUT"),
    RequiresActionError: ("provider_error", "AGENT_PROVIDER_REQUIRES_ACTION"),
    FoundryRunError: ("provider_error", "AGENT_PROVIDER_ERROR"),
}


class AgentCoordinator:
    def __init__(
        self,
        *,
        adapter: FoundryRemoteAgentAdapter,
        telemetry: TelemetryRecorder,
        contracts: ContractsRegistry,
        provider_display: str,
    ) -> None:
        self._adapter = adapter
        self._telemetry = telemetry
        self._contracts = contracts
        self._provider_display = provider_display
        self._data_analyst = DataAnalystAgent(adapter)
        self._recommender = SupportRecommendationAgent(adapter)
        self._validator = ValidatorAgent(adapter)

    def run(self, request: CoordinatorRequest) -> CoordinatorResult:
        trace: list[AgentTraceStep] = []
        trace_id = str(uuid.uuid4())
        deadline = time.monotonic() + ORCHESTRATION_TOTAL_BUDGET_SECONDS
        provider_model = self._provider_display

        sanitized_concern = sanitize_free_text(request.concern_text, max_len=CONCERN_TEXT_MAX_LEN)

        analyst_ctx = DataAnalystContext(
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

        analysis_result = self._call(
            DATA_ANALYST_NAME,
            lambda: self._data_analyst.analyze(analyst_ctx),
            trace=trace,
            provider_model=provider_model,
            deadline=deadline,
        )
        if isinstance(analysis_result, CoordinatorResult):
            return analysis_result

        env = self._envelope(
            source_agent="data-analyst-agent",
            target_agent="support-recommendation-agent",
            payload={
                **analysis_result.analysis.model_dump(),
                "synthetic_only": True,
            },
            trace_id=trace_id,
        )
        maybe_fail = self._protocol_validate(
            schema_name="data-analysis-result.schema.json",
            envelope=env,
            trace=trace,
            provider_model=provider_model,
            agent_name=DATA_ANALYST_NAME,
        )
        if maybe_fail is not None:
            return maybe_fail

        rec_ctx = SupportRecommenderContext(
            category=request.category,
            sanitized_concern_text=sanitized_concern,
            allowed_resources=request.allowed_resources,
            allowed_smart_goal_ids=request.allowed_smart_goal_ids,
            allowed_strategy_ids=request.allowed_strategy_ids,
        )

        draft_result = self._call(
            RECOMMENDER_NAME,
            lambda: self._recommender.recommend(
                analysis_result,
                rec_ctx,
                repair_guidance="",
            ),
            trace=trace,
            provider_model=provider_model,
            deadline=deadline,
        )
        if isinstance(draft_result, CoordinatorResult):
            return draft_result

        env = self._envelope(
            source_agent="support-recommendation-agent",
            target_agent="validator-agent",
            payload=self._recommender_payload(draft_result),
            trace_id=trace_id,
        )
        maybe_fail = self._protocol_validate(
            schema_name="support-recommendation-result.schema.json",
            envelope=env,
            trace=trace,
            provider_model=provider_model,
            agent_name=RECOMMENDER_NAME,
        )
        if maybe_fail is not None:
            return maybe_fail

        validator_ctx = ValidatorContext(
            allowed_resource_ids=tuple(r.id for r in request.allowed_resources),
            allowed_smart_goal_ids=request.allowed_smart_goal_ids,
            allowed_strategy_ids=request.allowed_strategy_ids,
            required_contract_version=CONTRACT_VERSION,
        )

        report = self._validate(
            analysis_result,
            draft_result,
            validator_ctx,
            trace,
            provider_model,
            deadline,
        )
        if isinstance(report, CoordinatorResult):
            return report

        env = self._envelope(
            source_agent="validator-agent",
            target_agent="coordinator",
            payload=self._validator_payload(report),
            trace_id=trace_id,
        )
        maybe_fail = self._protocol_validate(
            schema_name="validation-result.schema.json",
            envelope=env,
            trace=trace,
            provider_model=provider_model,
            agent_name=VALIDATOR_NAME,
        )
        if maybe_fail is not None:
            return maybe_fail

        if not report.passed:
            repair_guidance = _sanitize_repair(report.repair_guidance)
            repair_result = self._call(
                RECOMMENDER_NAME + ":repair",
                lambda: self._recommender.recommend(
                    analysis_result,
                    rec_ctx,
                    repair_guidance=repair_guidance,
                ),
                trace=trace,
                provider_model=provider_model,
                deadline=deadline,
            )
            if isinstance(repair_result, CoordinatorResult):
                return repair_result
            draft_result = repair_result

            env = self._envelope(
                source_agent="support-recommendation-agent",
                target_agent="validator-agent",
                payload=self._recommender_payload(draft_result),
                trace_id=trace_id,
            )
            maybe_fail = self._protocol_validate(
                schema_name="support-recommendation-result.schema.json",
                envelope=env,
                trace=trace,
                provider_model=provider_model,
                agent_name=RECOMMENDER_NAME + ":repair",
            )
            if maybe_fail is not None:
                return maybe_fail

            report = self._validate(
                analysis_result,
                draft_result,
                validator_ctx,
                trace,
                provider_model,
                deadline,
                use_llm_critique=False,
            )
            if isinstance(report, CoordinatorResult):
                return report

            env = self._envelope(
                source_agent="validator-agent",
                target_agent="coordinator",
                payload=self._validator_payload(report),
                trace_id=trace_id,
            )
            maybe_fail = self._protocol_validate(
                schema_name="validation-result.schema.json",
                envelope=env,
                trace=trace,
                provider_model=provider_model,
                agent_name=VALIDATOR_NAME,
            )
            if maybe_fail is not None:
                return maybe_fail

            if not report.passed:
                return CoordinatorResult(
                    status="validation_failed",
                    error_code="VALIDATION_FAILED_AFTER_REPAIR",
                    error_message=(
                        "Recommendation could not be validated after one repair "
                        "attempt. No recommendation is returned."
                    ),
                    recommendation=None,
                    agent_trace=trace,
                    provider_model=provider_model,
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
            agent_trace=trace,
            provider_model=provider_model,
        )

    def _envelope(
        self,
        *,
        source_agent: str,
        target_agent: str | None,
        payload: dict[str, Any],
        trace_id: str,
    ) -> dict[str, Any]:
        env: dict[str, Any] = {
            "schema_version": "1.0.0",
            "message_id": str(uuid.uuid4()),
            "trace_id": trace_id,
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
        trace: list[AgentTraceStep],
        provider_model: str,
        agent_name: str,
    ) -> CoordinatorResult | None:
        try:
            self._contracts.validate(schema_name, envelope)
        except ContractValidationError as exc:
            trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status="failed",
                    provider="azure_foundry_agents",
                    model="remote",
                    latency_ms=0,
                    token_estimate=None,
                    issue_codes=["PROTOCOL_VALIDATION_FAILED"],
                )
            )
            return CoordinatorResult(
                status="invalid_model_json",
                error_code="PROTOCOL_VALIDATION_FAILED",
                error_message=(
                    f"Message failed protocol validation " f"({schema_name}: {exc.safe_reason})."
                ),
                recommendation=None,
                agent_trace=trace,
                provider_model=provider_model,
            )
        return None

    @staticmethod
    def _recommender_payload(draft: SupportRecommendationDraft) -> dict[str, Any]:
        return {
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
            "synthetic_only": True,
        }

    @staticmethod
    def _validator_payload(report: ValidatorReport) -> dict[str, Any]:
        return {
            "passed": report.passed,
            "issue_codes": list(report.issue_codes),
            "warning_codes": list(report.warning_codes),
            "repair_guidance": report.repair_guidance,
            "synthetic_only": True,
        }

    def _call(
        self,
        agent_name: str,
        fn: Callable[[], _T],
        *,
        trace: list[AgentTraceStep],
        provider_model: str,
        deadline: float,
    ) -> _T | CoordinatorResult:
        if time.monotonic() >= deadline:
            trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status="budget_exhausted",
                    provider="azure_foundry_agents",
                    model="remote",
                    latency_ms=0,
                    token_estimate=None,
                    issue_codes=["ORCHESTRATION_BUDGET_EXHAUSTED"],
                )
            )
            return CoordinatorResult(
                status="orchestration_budget_exhausted",
                error_code="ORCHESTRATION_BUDGET_EXHAUSTED",
                error_message="Orchestration exceeded total budget.",
                recommendation=None,
                agent_trace=trace,
                provider_model=provider_model,
            )
        started = time.monotonic()
        try:
            result = fn()
        except FoundryProviderError as exc:
            latency = int((time.monotonic() - started) * 1000)
            status, code = _classify_provider_error(exc)
            trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status=status,
                    provider="azure_foundry_agents",
                    model="remote",
                    latency_ms=latency,
                    token_estimate=None,
                    issue_codes=[code],
                )
            )
            self._telemetry.record(
                "agent_call",
                {"agent": agent_name, "status": status, "latency_ms": latency},
            )
            return CoordinatorResult(
                status=status,
                error_code=code,
                error_message=_safe_message(status),
                recommendation=None,
                agent_trace=trace,
                provider_model=provider_model,
            )
        except ValueError as exc:
            latency = int((time.monotonic() - started) * 1000)
            code = str(exc) or "invalid_model_json"
            trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status="invalid_model_json",
                    provider="azure_foundry_agents",
                    model="remote",
                    latency_ms=latency,
                    token_estimate=None,
                    issue_codes=[f"AGENT_INVALID_JSON:{code}"],
                )
            )
            return CoordinatorResult(
                status="invalid_model_json",
                error_code="AGENT_INVALID_JSON",
                error_message="Remote agent returned invalid or off-schema JSON.",
                recommendation=None,
                agent_trace=trace,
                provider_model=provider_model,
            )
        latency = int((time.monotonic() - started) * 1000)
        trace.append(
            AgentTraceStep(
                agent=agent_name,
                status="ok",
                provider="azure_foundry_agents",
                model="remote",
                latency_ms=latency,
                token_estimate=None,
            )
        )
        self._telemetry.record(
            "agent_call",
            {"agent": agent_name, "status": "ok", "latency_ms": latency},
        )
        return result

    def _validate(
        self,
        analysis: DataAnalystOutput,
        draft: SupportRecommendationDraft,
        ctx: ValidatorContext,
        trace: list[AgentTraceStep],
        provider_model: str,
        deadline: float,
        *,
        use_llm_critique: bool = True,
    ) -> ValidatorReport | CoordinatorResult:
        if time.monotonic() >= deadline:
            trace.append(
                AgentTraceStep(
                    agent=VALIDATOR_NAME,
                    status="budget_exhausted",
                    provider="azure_foundry_agents",
                    model="remote",
                    latency_ms=0,
                    token_estimate=None,
                    issue_codes=["ORCHESTRATION_BUDGET_EXHAUSTED"],
                )
            )
            return CoordinatorResult(
                status="orchestration_budget_exhausted",
                error_code="ORCHESTRATION_BUDGET_EXHAUSTED",
                error_message="Orchestration exceeded total budget.",
                recommendation=None,
                agent_trace=trace,
                provider_model=provider_model,
            )
        started = time.monotonic()
        report = self._validator.validate(
            ValidatorInput(analysis=analysis, draft=draft, context=ctx),
            use_llm_critique=use_llm_critique,
        )
        latency = int((time.monotonic() - started) * 1000)
        trace.append(
            AgentTraceStep(
                agent=VALIDATOR_NAME,
                status="passed" if report.passed else "failed",
                provider="azure_foundry_agents",
                model="remote",
                latency_ms=latency,
                token_estimate=None,
                issue_codes=list(report.issue_codes),
                warning_codes=list(report.warning_codes),
            )
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
        "Run scripts/sync_foundry_agents.py --apply."
    ),
}


def _safe_message(status: str) -> str:
    return _SAFE_MESSAGES.get(status, "Unknown remote agent error.")


def _sanitize_repair(text: str) -> str:
    return text[:800]


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
        completeness={
            "ok": report.passed,
            "missing": list(report.issue_codes),
        },
        generated_by=generated_by,
    )
