"""Support Recommendation Agent - remote Foundry agent invocation.

Coordinator-supplied group-scoped evidence is:
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
from ..shared.prompt_blocks import wrap_untrusted
from ..shared.responses import parse_role_response

AGENT_ID = "support-recommender"
AGENT_NAME = "support-recommendation-agent"


@dataclass(frozen=True)
class SupportRecommenderContext:
    dealer_group_id: str
    category: str
    concern_text: str
    allowed_resources: tuple[ResourceRef, ...]
    allowed_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]
    evidence: EvidenceBundle


def _build_prompt(
    analysis: DataAnalystOutput,
    context: SupportRecommenderContext,
    repair_guidance: str,
) -> str:
    """Every block is fenced as untrusted, including prior agent output.

    A previous agent's JSON is still model-generated text, so it gets the
    same treatment as the concern a person typed.
    """

    allowed = {
        "resource_ids": [r.id for r in context.allowed_resources],
        "goal_ids": list(context.allowed_goal_ids),
        "strategy_ids": list(context.allowed_strategy_ids),
        "citation_ids": [c.citation_id for c in context.evidence.citations],
    }
    evidence = [
        {
            "citation_id": c.citation_id,
            "source_type": c.source_type.value,
            "source_title": c.source_title,
            "evidence_summary": c.evidence_summary,
        }
        for c in context.evidence.citations
    ]
    blocks = [
        wrap_untrusted(
            "prior_agent_output_data_analyst",
            json.dumps(analysis.model_dump(mode="json")),
        ),
        wrap_untrusted("allowed_ids", json.dumps(allowed)),
        wrap_untrusted("group_evidence", json.dumps(evidence)),
        wrap_untrusted("concern_text", context.concern_text),
        wrap_untrusted("validator_repair_guidance", repair_guidance) if repair_guidance else "",
    ]
    return f"Category: {context.category}. Produce a SupportRecommendationDraft.\n" + "\n".join(
        blocks
    )


def _attach_citations(
    output: SupportRecommendationModelOutput,
    context: SupportRecommenderContext,
) -> SupportRecommendationDraft:
    """Swap the model's citation *ids* for the retriever's citation *objects*.

    The model chooses which evidence supports its draft, but never authors the
    evidence text. An id it invented is dropped, and an empty result stays
    empty: attaching every retrieved citation would let an ungrounded draft
    pass the validator's citation check.
    """

    by_id = {c.citation_id: c for c in context.evidence.citations}
    citations: tuple[Citation, ...] = tuple(by_id[cid] for cid in output.cited_ids if cid in by_id)

    payload = output.model_dump(mode="json")
    payload.pop("cited_ids", None)
    payload["dealer_group_id"] = context.dealer_group_id
    payload["citations"] = [c.model_dump(mode="json") for c in citations]

    try:
        return SupportRecommendationDraft.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("invalid_draft_schema") from exc


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
        response = await self._runtime.invoke(
            role=AGENT_NAME,
            user_message=_build_prompt(analysis, context, repair_guidance),
            response_model=SupportRecommendationModelOutput,
            deadline=deadline,
        )
        output = parse_role_response(response, SupportRecommendationModelOutput)
        return _attach_citations(output, context)
