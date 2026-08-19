"""Support Recommendation Agent - thin adapter over LocalManifestAgentAdapter.

Instructions live in /agents/support-recommender/agent.md. Runtime metadata
lives in /agents/support-recommender/manifest.yaml.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..adapter import LocalManifestAgentAdapter
from ..shared.contracts import DataAnalystOutput, ResourceRef, SupportRecommendationDraft
from ..shared.sanitization import wrap_untrusted

if TYPE_CHECKING:
    from ...llm import LlmProvider

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
    def __init__(self, provider: LlmProvider) -> None:
        self._adapter = LocalManifestAgentAdapter(AGENT_ID, provider)

    @property
    def system_prompt(self) -> str:
        return self._adapter.system_prompt

    @property
    def spec_version(self) -> str:
        return self._adapter.manifest.version

    def recommend(
        self,
        analysis: DataAnalystOutput,
        context: SupportRecommenderContext,
        *,
        repair_guidance: str = "",
        max_tokens: int,
        timeout_seconds: float,
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

        payload = self._adapter.call(
            user_prompt=user_prompt,
            response_schema_name="support_recommendation_draft",
            max_output_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        try:
            return SupportRecommendationDraft.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("invalid_draft_schema") from exc
