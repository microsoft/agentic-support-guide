"""Support Recommendation Agent - remote Foundry agent invocation.

Coordinator-supplied district-scoped evidence is:
- passed to the remote agent as an untrusted `allowed_citations` block
  so the agent can decide which citations support its draft,
- also attached to the returned draft by this Python wrapper, filtered
  to the citation IDs the remote agent selected.

If the remote agent selects no citations, `SupportRecommendationDraft.citations`
is empty and the Validator Agent will fail the draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ...evidence import EvidenceBundle
from ...foundry_agents.maf_runtime import MafAgentRuntime
from ..shared.contracts import (
    Citation,
    DataAnalystOutput,
    ResourceRef,
    SupportRecommendationDraft,
    SupportRecommendationModelOutput,
)
from ..shared.responses import parse_role_response
from ..shared.sanitization import wrap_untrusted

AGENT_ID = "support-recommender"
AGENT_NAME = "support-recommendation-agent"


@dataclass(frozen=True)
class SupportRecommenderContext:
    district_id: str
    category: str
    sanitized_concern_text: str
    allowed_resources: tuple[ResourceRef, ...]
    allowed_smart_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]
    evidence: EvidenceBundle


class SupportRecommendationAgent:
    def __init__(self, runtime: MafAgentRuntime) -> None:
        self._runtime = runtime

    async def recommend(
        self,
        analysis: DataAnalystOutput,
        context: SupportRecommenderContext,
        *,
        repair_guidance: str = "",
        deadline: float | None = None,
    ) -> SupportRecommendationDraft:
        allowed = {
            "resource_ids": [r.id for r in context.allowed_resources],
            "smart_goal_ids": list(context.allowed_smart_goal_ids),
            "strategy_ids": list(context.allowed_strategy_ids),
            "citation_ids": [c.citation_id for c in context.evidence.citations],
        }
        analyst_block = wrap_untrusted(
            "prior_agent_output_data_analyst",
            json.dumps(analysis.model_dump(mode="json")),
        )
        allowed_block = wrap_untrusted("allowed_ids", json.dumps(allowed))
        evidence_block = wrap_untrusted(
            "district_evidence",
            json.dumps(
                [
                    {
                        "citation_id": c.citation_id,
                        "source_type": c.source_type.value,
                        "source_title": c.source_title,
                        "evidence_summary": c.evidence_summary,
                    }
                    for c in context.evidence.citations
                ]
            ),
        )
        concern_block = wrap_untrusted("concern_text", context.sanitized_concern_text)
        repair_block = (
            wrap_untrusted("validator_repair_guidance", repair_guidance) if repair_guidance else ""
        )
        user_prompt = (
            f"Category: {context.category}. Produce a SupportRecommendationDraft.\n"
            f"{analyst_block}\n{allowed_block}\n{evidence_block}\n{concern_block}\n{repair_block}"
        )

        response = await self._runtime.invoke(
            role=AGENT_NAME,
            user_message=user_prompt,
            response_model=SupportRecommendationModelOutput,
            deadline=deadline,
        )
        output = parse_role_response(response, SupportRecommendationModelOutput)

        # Resolve cited IDs against the coordinator-supplied, district-scoped
        # bundle so the model cannot invent citation content. An empty list
        # stays empty: attaching every retrieved citation would let an
        # ungrounded draft pass the validator's citation check.
        by_id = {c.citation_id: c for c in context.evidence.citations}
        citations: tuple[Citation, ...] = tuple(
            by_id[cid] for cid in output.cited_ids if cid in by_id
        )

        payload = output.model_dump(mode="json")
        payload.pop("cited_ids", None)
        payload["district_id"] = context.district_id
        payload["citations"] = [c.model_dump(mode="json") for c in citations]

        try:
            return SupportRecommendationDraft.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("invalid_draft_schema") from exc
