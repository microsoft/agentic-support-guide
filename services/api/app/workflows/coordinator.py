"""Agent Coordinator - orchestrates the three-agent workflow.

Sequence: build context -> Data Analyst -> validate contract -> Support
Recommender -> validate contract -> Validator -> optional single repair of
the recommender -> re-run deterministic validation once -> return.

Guarantees:
- No recursion, no repeated repair loops.
- Data Analyst is never re-run during repair.
- Unvalidated recommendations never leave the coordinator as successful.
- Trace metadata contains only safe generalized codes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

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
    AGENT_MAX_OUTPUT_TOKENS,
    AGENT_REQUEST_TIMEOUT_SECONDS,
    CONCERN_TEXT_MAX_LEN,
    ORCHESTRATION_TOTAL_BUDGET_SECONDS,
)
from ..llm import LlmError, LlmProvider
from ..models import AgentTraceStep, Recommendation, RecommendationResource
from ..telemetry import TelemetryRecorder

if TYPE_CHECKING:
    pass


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


ERROR_CATEGORY_TO_STATUS = {
    "timeout": "provider_timeout",
    "throttling": "provider_throttling",
    "content_filter": "provider_content_filter",
    "provider_error": "provider_error",
    "provider_missing": "provider_missing",
}


class AgentCoordinator:
    def __init__(
        self,
        *,
        provider: LlmProvider,
        telemetry: TelemetryRecorder,
    ) -> None:
        self._provider = provider
        self._telemetry = telemetry
        self._data_analyst = DataAnalystAgent(provider)
        self._recommender = SupportRecommendationAgent(provider)
        self._validator = ValidatorAgent(provider)

    def run(self, request: CoordinatorRequest) -> CoordinatorResult:
        trace: list[AgentTraceStep] = []
        deadline = time.monotonic() + ORCHESTRATION_TOTAL_BUDGET_SECONDS
        provider_model = f"{self._provider.name} / {self._provider.model}"

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
            lambda: self._data_analyst.analyze(
                analyst_ctx,
                max_tokens=AGENT_MAX_OUTPUT_TOKENS,
                timeout_seconds=self._remaining(deadline),
            ),
            trace=trace,
            provider_model=provider_model,
            deadline=deadline,
        )
        if isinstance(analysis_result, CoordinatorResult):
            return analysis_result

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
                max_tokens=AGENT_MAX_OUTPUT_TOKENS,
                timeout_seconds=self._remaining(deadline),
            ),
            trace=trace,
            provider_model=provider_model,
            deadline=deadline,
        )
        if isinstance(draft_result, CoordinatorResult):
            return draft_result

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

        if not report.passed:
            repair_guidance = _sanitize_repair(report.repair_guidance)
            repair_result = self._call(
                RECOMMENDER_NAME + ":repair",
                lambda: self._recommender.recommend(
                    analysis_result,
                    rec_ctx,
                    repair_guidance=repair_guidance,
                    max_tokens=AGENT_MAX_OUTPUT_TOKENS,
                    timeout_seconds=self._remaining(deadline),
                ),
                trace=trace,
                provider_model=provider_model,
                deadline=deadline,
            )
            if isinstance(repair_result, CoordinatorResult):
                return repair_result
            draft_result = repair_result
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
            provider_display=self._provider.display_name,
        )
        return CoordinatorResult(
            status="ok",
            error_code=None,
            error_message=None,
            recommendation=recommendation,
            agent_trace=trace,
            provider_model=provider_model,
        )

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        return max(1.0, min(AGENT_REQUEST_TIMEOUT_SECONDS, remaining))

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
                    provider=self._provider.name,
                    model=self._provider.model,
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
        except LlmError as exc:
            latency = int((time.monotonic() - started) * 1000)
            status = ERROR_CATEGORY_TO_STATUS.get(exc.category, "provider_error")
            code = f"AGENT_{status.upper()}"
            trace.append(
                AgentTraceStep(
                    agent=agent_name,
                    status=status,
                    provider=self._provider.name,
                    model=self._provider.model,
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
                    provider=self._provider.name,
                    model=self._provider.model,
                    latency_ms=latency,
                    token_estimate=None,
                    issue_codes=[f"AGENT_INVALID_JSON:{code}"],
                )
            )
            return CoordinatorResult(
                status="invalid_model_json",
                error_code="AGENT_INVALID_JSON",
                error_message="Model returned invalid or off-schema JSON.",
                recommendation=None,
                agent_trace=trace,
                provider_model=provider_model,
            )
        latency = int((time.monotonic() - started) * 1000)
        trace.append(
            AgentTraceStep(
                agent=agent_name,
                status="ok",
                provider=self._provider.name,
                model=self._provider.model,
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
                    provider=self._provider.name,
                    model=self._provider.model,
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
            max_tokens=AGENT_MAX_OUTPUT_TOKENS,
            timeout_seconds=self._remaining(deadline),
        )
        latency = int((time.monotonic() - started) * 1000)
        trace.append(
            AgentTraceStep(
                agent=VALIDATOR_NAME,
                status="passed" if report.passed else "failed",
                provider=self._provider.name,
                model=self._provider.model,
                latency_ms=latency,
                token_estimate=None,
                issue_codes=list(report.issue_codes),
                warning_codes=list(report.warning_codes),
            )
        )
        return report


_SAFE_MESSAGES = {
    "provider_timeout": "Model provider timed out.",
    "provider_throttling": "Model provider throttled the request.",
    "provider_content_filter": "Model provider blocked the request via content safety.",
    "provider_error": "Model provider returned an error.",
    "provider_missing": "Model provider configuration is missing.",
}


def _safe_message(status: str) -> str:
    return _SAFE_MESSAGES.get(status, "Unknown provider error.")


def _sanitize_repair(text: str) -> str:
    # Only structured template lines produced by the validator can pass. The
    # LLM critique text was intentionally coerced through fixed templates in
    # the Validator; here we just cap length.
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
