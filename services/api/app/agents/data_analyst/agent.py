"""Data Analyst Agent - remote Foundry agent invocation.

The Python wrapper attaches `district_id` (from context) to the parsed
model output. The remote agent itself does not need to know about
`district_id`; the coordinator is the source of truth for tenant
boundaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ...foundry_agents.maf_runtime import MafAgentRuntime
from ..shared.contracts import DataAnalystModelOutput, DataAnalystOutput
from ..shared.responses import parse_role_response
from ..shared.sanitization import wrap_untrusted

AGENT_ID = "data-analyst"
AGENT_NAME = "data-analyst-agent"


@dataclass(frozen=True)
class DataAnalystContext:
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
    sanitized_concern_text: str


class DataAnalystAgent:
    def __init__(self, runtime: MafAgentRuntime) -> None:
        self._runtime = runtime

    async def analyze(
        self, context: DataAnalystContext, *, deadline: float | None = None
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
        response = await self._runtime.invoke(
            role=AGENT_NAME,
            user_message=user_prompt,
            response_model=DataAnalystModelOutput,
            deadline=deadline,
        )
        output = parse_role_response(response, DataAnalystModelOutput)
        return DataAnalystOutput(
            contract_version=output.contract_version,
            district_id=context.district_id,
            analysis=output.analysis,
            citations=[],
        )
