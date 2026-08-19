"""Data Analyst Agent - remote Foundry agent invocation.

The role-specific prompt template and expected schema live here. The
underlying LLM call is delegated to a remote Azure AI Foundry Agent
Service assistant via FoundryRemoteAgentAdapter. There is no local
model call and no local fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ...foundry_agents import FoundryRemoteAgentAdapter
from ..shared.contracts import AnalysisSummary, DataAnalystOutput
from ..shared.sanitization import wrap_untrusted

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
    def __init__(self, adapter: FoundryRemoteAgentAdapter) -> None:
        self._adapter = adapter

    def analyze(self, context: DataAnalystContext) -> DataAnalystOutput:
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
        response = self._adapter.invoke(role=AGENT_NAME, user_message=user_prompt)
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_model_json") from exc
        try:
            analysis = AnalysisSummary.model_validate(payload.get("analysis", {}))
        except ValidationError as exc:
            raise ValueError("invalid_analysis_schema") from exc
        return DataAnalystOutput(
            contract_version=payload.get("contract_version", "1.0.0"),
            analysis=analysis,
        )
