"""Data Analyst Agent - remote Foundry agent invocation.

The Python wrapper attaches `dealer_group_id` (from context) to the parsed
model output. The remote agent itself does not need to know about
`dealer_group_id`; the coordinator is the source of truth for tenant
boundaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ...foundry_agents.maf_runtime import MafAgentRuntime
from ...operations import OperationsSeries
from ...scores import AreaSeries
from ..shared.contracts import DataAnalystModelOutput, DataAnalystOutput
from ..shared.prompt_blocks import wrap_untrusted
from ..shared.responses import parse_role_response

AGENT_ID = "data-analyst"
AGENT_NAME = "data-analyst-agent"


@dataclass(frozen=True)
class DataAnalystContext:
    dealer_group_id: str
    dealership_label: str
    region_id: str
    segment: str
    process_score: float
    appointment_attendance_rate: float
    followup_index: float
    engagement_index: float
    area_series: AreaSeries
    operations_series: OperationsSeries
    category: str
    concern_text: str


class DataAnalystAgent:
    def __init__(self, runtime: MafAgentRuntime) -> None:
        self._runtime = runtime

    async def analyze(
        self, context: DataAnalystContext, *, deadline: float | None = None
    ) -> DataAnalystOutput:
        # The series, not just their size. Sending only a record count left
        # the model with nothing to compare across areas or over time, which
        # is the whole analysis this agent is asked for.
        areas = context.area_series
        ops = context.operations_series
        facts = {
            "dealership_label": context.dealership_label,
            "region_id": context.region_id,
            "segment": context.segment,
            "process_score": context.process_score,
            "appointment_attendance_rate": context.appointment_attendance_rate,
            "followup_index": context.followup_index,
            "engagement_index": context.engagement_index,
            "category": context.category,
            "score_periods": list(areas.periods),
            "score_by_process_area": {
                area: list(values) for area, values in areas.scores_by_area.items()
            },
            "latest_band_by_process_area": dict(areas.latest_band_by_area),
            "area_score_count": areas.record_count,
            "duplicate_area_records": areas.duplicate_count,
            "operations_periods": list(ops.periods),
            "appointment_attendance_rate_by_period": list(ops.appointment_attendance_rate),
            "escalations_by_period": list(ops.escalations),
            "followup_completion_by_period": list(ops.followup_completion),
            "operations_record_count": ops.record_count,
        }
        user_prompt = (
            "Analyze the synthetic dealership indicators below and produce the "
            "structured output required by your instructions.\n"
            + wrap_untrusted("synthetic_facts", json.dumps(facts))
            + "\n"
            + wrap_untrusted("concern_text", context.concern_text)
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
            dealer_group_id=context.dealer_group_id,
            analysis=output.analysis,
            citations=[],
        )
