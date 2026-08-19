"""Data Analyst Agent - thin adapter over LocalManifestAgentAdapter.

Instructions live in /agents/data-analyst/agent.md. Runtime metadata
lives in /agents/data-analyst/manifest.yaml. No role-specific prompt
text lives in Python.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..adapter import LocalManifestAgentAdapter
from ..shared.contracts import AnalysisSummary, DataAnalystOutput
from ..shared.sanitization import wrap_untrusted

if TYPE_CHECKING:
    from ...llm import LlmProvider

AGENT_ID = "data-analyst"
AGENT_NAME = "data-analyst-agent"


@dataclass(frozen=True)
class DataAnalystContext:
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
    sanitized_concern_text: str


class DataAnalystAgent:
    def __init__(self, provider: LlmProvider) -> None:
        self._adapter = LocalManifestAgentAdapter(AGENT_ID, provider)

    @property
    def system_prompt(self) -> str:
        return self._adapter.system_prompt

    @property
    def spec_version(self) -> str:
        return self._adapter.manifest.version

    def analyze(
        self, context: DataAnalystContext, *, max_tokens: int, timeout_seconds: float
    ) -> DataAnalystOutput:
        facts = {
            "learner_label": context.learner_label,
            "grade": context.grade,
            "school_id": context.school_id,
            "group": context.group,
            "proficiency_index": context.proficiency_index,
            "attendance_rate": context.attendance_rate,
            "behavior_index": context.behavior_index,
            "engagement_index": context.engagement_index,
            "assessment_count": context.assessment_count,
            "behavior_record_count": context.behavior_record_count,
            "category": context.category,
        }
        user_prompt = (
            "Analyze the synthetic learner indicators below and produce the "
            "structured output required by your instructions.\n"
            + wrap_untrusted("synthetic_facts", json.dumps(facts))
            + "\n"
            + wrap_untrusted("concern_text", context.sanitized_concern_text)
        )

        payload = self._adapter.call(
            user_prompt=user_prompt,
            response_schema_name="data_analyst_output",
            max_output_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        try:
            analysis = AnalysisSummary.model_validate(payload.get("analysis", {}))
        except ValidationError as exc:
            raise ValueError("invalid_analysis_schema") from exc
        return DataAnalystOutput(
            contract_version=payload.get("contract_version", "1.0.0"),
            analysis=analysis,
        )
