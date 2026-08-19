"""Support Recommendation Agent - remote Foundry agent invocation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ...foundry_agents import FoundryRemoteAgentAdapter
from ..shared.contracts import DataAnalystOutput, ResourceRef, SupportRecommendationDraft
from ..shared.sanitization import wrap_untrusted

AGENT_ID = "support-recommender"
AGENT_NAME = "support-recommendation-agent"


@dataclass(frozen=True)
class SupportRecommenderContext:
    category: str
    sanitized_concern_text: str
    allowed_resources: tuple[ResourceRef, ...]
    allowed_smart_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]


class SupportRecommendationAgent:
    def __init__(self, adapter: FoundryRemoteAgentAdapter) -> None:
        self._adapter = adapter

    def recommend(
        self,
        analysis: DataAnalystOutput,
        context: SupportRecommenderContext,
        *,
        repair_guidance: str = "",
    ) -> SupportRecommendationDraft:
        allowed = {
            "resource_ids": [r.id for r in context.allowed_resources],
            "smart_goal_ids": list(context.allowed_smart_goal_ids),
            "strategy_ids": list(context.allowed_strategy_ids),
        }
        analyst_block = wrap_untrusted(
            "prior_agent_output_data_analyst",
            json.dumps(analysis.model_dump()),
        )
        allowed_block = wrap_untrusted("allowed_ids", json.dumps(allowed))
        concern_block = wrap_untrusted("concern_text", context.sanitized_concern_text)
        repair_block = (
            wrap_untrusted("validator_repair_guidance", repair_guidance) if repair_guidance else ""
        )
        user_prompt = (
            f"Category: {context.category}. Produce a SupportRecommendationDraft.\n"
            f"{analyst_block}\n{allowed_block}\n{concern_block}\n{repair_block}"
        )
        response = self._adapter.invoke(role=AGENT_NAME, user_message=user_prompt)
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_model_json") from exc
        try:
            return SupportRecommendationDraft.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("invalid_draft_schema") from exc
