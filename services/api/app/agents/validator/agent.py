"""Validator Agent.

Deterministic Python checks decide pass/fail. The optional remote LLM
critique may only add advisory warning codes. Repair guidance is drawn
from a fixed template set. Raw model critique never reaches the UI or
audit trail.

Validator checks in this iteration:

- contract-version match,
- allowed resource / SMART goal / strategy IDs,
- required caveats (including "human review"),
- required support-tier framing,
- required progress-monitoring and next steps,
- rationale is non-empty,
- **at least one citation** on the draft,
- **every citation.district_id matches the request district_id**,
- **every citation_id is in the allowed set** produced by the retriever,
- no policy/placement/legal/medical determinations (via keyword scan).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ...foundry_agents.errors import FoundryProviderError
from ...foundry_agents.maf_runtime import MafAgentRuntime
from ..shared.contracts import (
    DataAnalystOutput,
    SupportRecommendationDraft,
    ValidatorCritiqueModelOutput,
    ValidatorReport,
)
from ..shared.responses import parse_role_response
from ..shared.sanitization import enforce_code, wrap_untrusted

AGENT_ID = "validator"
AGENT_NAME = "validator-agent"

REQUIRED_KEYWORD_CAVEATS = ("human review",)
REQUIRED_TIER_PATTERNS = ("universal", "targeted", "intensive", "enrichment")

# Determinations forbidden anywhere in draft free-text.
_FORBIDDEN_DETERMINATION_PATTERNS = (
    re.compile(r"\bdiagnos(is|e[ds]?|ing)\b", re.IGNORECASE),
    re.compile(r"\bplacement\s+decision\b", re.IGNORECASE),
    re.compile(r"\blegal(?:ly)?\s+determin", re.IGNORECASE),
    re.compile(r"\bmedical(?:ly)?\s+determin", re.IGNORECASE),
    re.compile(r"\bpolicy\s+determination\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ValidatorContext:
    district_id: str
    allowed_resource_ids: tuple[str, ...]
    allowed_smart_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]
    allowed_citation_ids: tuple[str, ...]
    required_contract_version: str


@dataclass(frozen=True)
class ValidatorInput:
    analysis: DataAnalystOutput
    draft: SupportRecommendationDraft
    context: ValidatorContext


class ValidatorAgent:
    def __init__(self, runtime: MafAgentRuntime) -> None:
        self._runtime = runtime

    async def validate(
        self,
        payload: ValidatorInput,
        *,
        use_llm_critique: bool,
        deadline: float | None = None,
    ) -> ValidatorReport:
        issue_codes: list[str] = []
        failed_fields: list[str] = []

        # Contract version.
        if payload.draft.contract_version != payload.context.required_contract_version:
            issue_codes.append("CONTRACT_VERSION_MISMATCH")
            failed_fields.append("contract_version")
        if payload.analysis.contract_version != payload.context.required_contract_version:
            issue_codes.append("CONTRACT_VERSION_MISMATCH")

        # District boundary on the draft itself.
        if payload.draft.district_id != payload.context.district_id:
            issue_codes.append("DRAFT_DISTRICT_MISMATCH")
            failed_fields.append("district_id")

        # Catalog membership.
        allowed_res = set(payload.context.allowed_resource_ids)
        unknown_res = [rid for rid in payload.draft.resource_ids if rid not in allowed_res]
        if unknown_res:
            issue_codes.append("UNKNOWN_RESOURCE_ID")
            failed_fields.append("resource_ids")

        allowed_goals = set(payload.context.allowed_smart_goal_ids)
        if any(gid not in allowed_goals for gid in payload.draft.smart_goal_suggestions):
            issue_codes.append("UNKNOWN_SMART_GOAL_ID")
            failed_fields.append("smart_goal_suggestions")

        allowed_strategies = set(payload.context.allowed_strategy_ids)
        if any(sid not in allowed_strategies for sid in payload.draft.strategy_suggestions):
            issue_codes.append("UNKNOWN_STRATEGY_ID")
            failed_fields.append("strategy_suggestions")

        # Citation checks - the core evidence-backed requirement.
        allowed_citations = set(payload.context.allowed_citation_ids)
        if not payload.draft.citations:
            issue_codes.append("MISSING_CITATIONS")
            failed_fields.append("citations")
        else:
            for c in payload.draft.citations:
                if c.district_id != payload.context.district_id:
                    issue_codes.append("CROSS_DISTRICT_CITATION")
                    if "citations" not in failed_fields:
                        failed_fields.append("citations")
                if c.citation_id not in allowed_citations:
                    issue_codes.append("UNKNOWN_CITATION_ID")
                    if "citations" not in failed_fields:
                        failed_fields.append("citations")

        # Caveats.
        if not payload.draft.caveats:
            issue_codes.append("MISSING_CAVEATS")
            failed_fields.append("caveats")
        else:
            caveat_text = " ".join(payload.draft.caveats).lower()
            if not all(keyword in caveat_text for keyword in REQUIRED_KEYWORD_CAVEATS):
                issue_codes.append("MISSING_HUMAN_REVIEW_CAVEAT")
                failed_fields.append("caveats")

        # Tier framing.
        tier_lower = payload.draft.support_tier.lower()
        if not any(pat in tier_lower for pat in REQUIRED_TIER_PATTERNS):
            issue_codes.append("INVALID_SUPPORT_TIER")
            failed_fields.append("support_tier")

        # Required lists.
        if not payload.draft.progress_monitoring:
            issue_codes.append("MISSING_PROGRESS_MONITORING")
            failed_fields.append("progress_monitoring")
        if not payload.draft.educator_next_steps:
            issue_codes.append("MISSING_NEXT_STEPS")
            failed_fields.append("educator_next_steps")
        if not payload.draft.rationale.strip():
            issue_codes.append("MISSING_RATIONALE")
            failed_fields.append("rationale")

        # Forbidden determinations in free-text.
        haystack = " ".join(
            [payload.draft.rationale, payload.draft.decision_rule, *payload.draft.caveats]
        )
        for pat in _FORBIDDEN_DETERMINATION_PATTERNS:
            if pat.search(haystack):
                issue_codes.append("FORBIDDEN_DETERMINATION")
                if "rationale" not in failed_fields:
                    failed_fields.append("rationale")
                break

        repair_guidance = _build_repair_guidance(issue_codes, unknown_res)
        warning_codes: list[str] = []

        if use_llm_critique and self._runtime.has_role(AGENT_NAME):
            try:
                # Advisory only: LLM critique may add warning codes.
                # Raw LLM repair text is intentionally discarded; repair
                # guidance must come from _REPAIR_TEMPLATES only.
                llm_warnings, _llm_repair_ignored = await self._llm_critique(
                    payload, deadline=deadline
                )
                warning_codes.extend(llm_warnings)
            except FoundryProviderError:
                warning_codes.append("VALIDATOR_LLM_CRITIQUE_UNAVAILABLE")
            except Exception:  # noqa: BLE001 - advisory only
                warning_codes.append("VALIDATOR_LLM_CRITIQUE_UNAVAILABLE")

        passed = not issue_codes
        safe_summary = _safe_summary(passed, sorted(set(issue_codes)))

        return ValidatorReport(
            district_id=payload.context.district_id,
            passed=passed,
            issue_codes=sorted(set(issue_codes)),
            warning_codes=sorted(set(warning_codes)),
            failed_fields=sorted(set(failed_fields)),
            safe_summary=safe_summary,
            repair_guidance=repair_guidance[:1000],
        )

    async def _llm_critique(
        self, payload: ValidatorInput, *, deadline: float | None = None
    ) -> tuple[list[str], str]:
        analyst_block = wrap_untrusted(
            "prior_agent_output_data_analyst",
            json.dumps(payload.analysis.model_dump(mode="json")),
        )
        draft_block = wrap_untrusted(
            "prior_agent_output_support_recommender",
            json.dumps(payload.draft.model_dump(mode="json")),
        )
        user_prompt = (
            "Critique the draft against the analyst evidence. Return only "
            "JSON: {warning_codes:string[], repair_guidance:string}. "
            "Warning codes must be uppercase snake case. Repair guidance "
            "must be under 500 characters.\n"
            f"{analyst_block}\n{draft_block}"
        )
        response = await self._runtime.invoke(
            role=AGENT_NAME,
            user_message=user_prompt,
            response_model=ValidatorCritiqueModelOutput,
            deadline=deadline,
        )
        try:
            critique = parse_role_response(response, ValidatorCritiqueModelOutput)
        except ValueError:
            return [], ""
        warnings: list[str] = []
        for w in critique.warning_codes:
            code = enforce_code(w) if isinstance(w, str) else None
            if code is not None:
                warnings.append(code)
        return warnings[:10], critique.repair_guidance


_REPAIR_TEMPLATES = {
    "UNKNOWN_RESOURCE_ID": (
        "Only reference resource ids from the allowed_ids block. Remove any invented ids."
    ),
    "UNKNOWN_SMART_GOAL_ID": ("Only reference SMART goal ids from the allowed_ids block."),
    "UNKNOWN_STRATEGY_ID": ("Only reference strategy ids from the allowed_ids block."),
    "MISSING_CITATIONS": (
        "Cite at least one citation from the district_evidence block. Recommendations without "
        "evidence are rejected."
    ),
    "CROSS_DISTRICT_CITATION": (
        "Every citation.district_id must match the request district_id. Remove or replace "
        "any cross-district citations."
    ),
    "UNKNOWN_CITATION_ID": ("Only cite citation_ids present in the district_evidence block."),
    "DRAFT_DISTRICT_MISMATCH": ("The draft district_id must match the request district_id."),
    "MISSING_CAVEATS": ("Add caveats that require human review before any use."),
    "MISSING_HUMAN_REVIEW_CAVEAT": ("Include an explicit 'human review is required' caveat."),
    "INVALID_SUPPORT_TIER": (
        "Support tier must reflect universal, targeted, intensive, or enrichment framing."
    ),
    "MISSING_PROGRESS_MONITORING": ("Add at least one progress-monitoring measure."),
    "MISSING_NEXT_STEPS": ("Add at least one educator next step."),
    "MISSING_RATIONALE": ("Provide a non-empty rationale grounded in the analyst evidence."),
    "CONTRACT_VERSION_MISMATCH": ("Set contract_version to the required value."),
    "FORBIDDEN_DETERMINATION": (
        "Remove any diagnosis, placement, legal, medical, or policy determination language."
    ),
}


def _build_repair_guidance(codes: list[str], unknown_res: list[str]) -> str:
    if not codes:
        return ""
    lines: list[str] = []
    for code in sorted(set(codes)):
        template = _REPAIR_TEMPLATES.get(code)
        if template:
            lines.append(f"- {template}")
    if unknown_res:
        lines.append(f"- Unknown resource ids: {sorted(unknown_res)[:5]}")
    return "\n".join(lines)


def _safe_summary(passed: bool, issue_codes: list[str]) -> str:
    if passed:
        return "Validator passed all deterministic checks."
    if not issue_codes:
        return "Validator failed with no coded reason."
    joined = ", ".join(issue_codes[:6])
    if len(issue_codes) > 6:
        joined += f", +{len(issue_codes) - 6} more"
    return f"Validator failed on: {joined}."
