"""Validator Agent.

Deterministic pass/fail plus optional LLM critique. Deterministic
checks are the source of truth. The LLM critique step delegates to a
remote Azure AI Foundry Agent Service assistant. If the remote critique
is not bound or fails, deterministic pass/fail still applies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ...foundry_agents import FoundryProviderError, FoundryRemoteAgentAdapter
from ..shared.contracts import (
    DataAnalystOutput,
    SupportRecommendationDraft,
    ValidatorReport,
)
from ..shared.sanitization import enforce_code, wrap_untrusted

AGENT_ID = "validator"
AGENT_NAME = "validator-agent"

REQUIRED_KEYWORD_CAVEATS = ("human review",)
REQUIRED_TIER_PATTERNS = ("universal", "targeted", "intensive", "enrichment")


@dataclass(frozen=True)
class ValidatorContext:
    allowed_resource_ids: tuple[str, ...]
    allowed_smart_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]
    required_contract_version: str


@dataclass(frozen=True)
class ValidatorInput:
    analysis: DataAnalystOutput
    draft: SupportRecommendationDraft
    context: ValidatorContext


class ValidatorAgent:
    def __init__(self, adapter: FoundryRemoteAgentAdapter) -> None:
        self._adapter = adapter

    def validate(
        self,
        payload: ValidatorInput,
        *,
        use_llm_critique: bool,
    ) -> ValidatorReport:
        issue_codes: list[str] = []

        if payload.draft.contract_version != payload.context.required_contract_version:
            issue_codes.append("CONTRACT_VERSION_MISMATCH")
        if payload.analysis.contract_version != payload.context.required_contract_version:
            issue_codes.append("CONTRACT_VERSION_MISMATCH")

        allowed_res = set(payload.context.allowed_resource_ids)
        unknown_res = [rid for rid in payload.draft.resource_ids if rid not in allowed_res]
        if unknown_res:
            issue_codes.append("UNKNOWN_RESOURCE_ID")

        allowed_goals = set(payload.context.allowed_smart_goal_ids)
        if any(gid not in allowed_goals for gid in payload.draft.smart_goal_suggestions):
            issue_codes.append("UNKNOWN_SMART_GOAL_ID")

        allowed_strategies = set(payload.context.allowed_strategy_ids)
        if any(sid not in allowed_strategies for sid in payload.draft.strategy_suggestions):
            issue_codes.append("UNKNOWN_STRATEGY_ID")

        if not payload.draft.caveats:
            issue_codes.append("MISSING_CAVEATS")
        else:
            caveat_text = " ".join(payload.draft.caveats).lower()
            if not all(keyword in caveat_text for keyword in REQUIRED_KEYWORD_CAVEATS):
                issue_codes.append("MISSING_HUMAN_REVIEW_CAVEAT")

        tier_lower = payload.draft.support_tier.lower()
        if not any(pat in tier_lower for pat in REQUIRED_TIER_PATTERNS):
            issue_codes.append("INVALID_SUPPORT_TIER")

        if not payload.draft.progress_monitoring:
            issue_codes.append("MISSING_PROGRESS_MONITORING")
        if not payload.draft.educator_next_steps:
            issue_codes.append("MISSING_NEXT_STEPS")
        if not payload.draft.rationale.strip():
            issue_codes.append("MISSING_RATIONALE")

        repair_guidance = _build_repair_guidance(issue_codes, unknown_res)
        warning_codes: list[str] = []

        if use_llm_critique and self._adapter.is_bound(AGENT_NAME):
            try:
                llm_warnings, llm_repair = self._llm_critique(payload)
                warning_codes.extend(llm_warnings)
                if llm_repair and not repair_guidance:
                    repair_guidance = llm_repair
            except FoundryProviderError:
                warning_codes.append("VALIDATOR_LLM_CRITIQUE_UNAVAILABLE")
            except Exception:  # noqa: BLE001 - advisory only
                warning_codes.append("VALIDATOR_LLM_CRITIQUE_UNAVAILABLE")

        return ValidatorReport(
            passed=not issue_codes,
            issue_codes=sorted(set(issue_codes)),
            warning_codes=sorted(set(warning_codes)),
            repair_guidance=repair_guidance[:1000],
        )

    def _llm_critique(self, payload: ValidatorInput) -> tuple[list[str], str]:
        analyst_block = wrap_untrusted(
            "prior_agent_output_data_analyst",
            json.dumps(payload.analysis.model_dump()),
        )
        draft_block = wrap_untrusted(
            "prior_agent_output_support_recommender",
            json.dumps(payload.draft.model_dump()),
        )
        user_prompt = (
            "Critique the draft against the analyst evidence. Return only "
            "JSON: {warning_codes:string[], repair_guidance:string}. "
            "Warning codes must be uppercase snake case. Repair guidance "
            "must be under 500 characters.\n"
            f"{analyst_block}\n{draft_block}"
        )
        response = self._adapter.invoke(role=AGENT_NAME, user_message=user_prompt)
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return [], ""
        warnings_raw = data.get("warning_codes") or []
        repair_raw = data.get("repair_guidance") or ""
        warnings: list[str] = []
        if isinstance(warnings_raw, list):
            for w in warnings_raw:
                code = enforce_code(w) if isinstance(w, str) else None
                if code is not None:
                    warnings.append(code)
        repair = repair_raw if isinstance(repair_raw, str) else ""
        return warnings[:10], repair


_REPAIR_TEMPLATES = {
    "UNKNOWN_RESOURCE_ID": (
        "Only reference resource ids from the allowed_ids block. Remove any invented ids."
    ),
    "UNKNOWN_SMART_GOAL_ID": ("Only reference SMART goal ids from the allowed_ids block."),
    "UNKNOWN_STRATEGY_ID": ("Only reference strategy ids from the allowed_ids block."),
    "MISSING_CAVEATS": ("Add caveats that require human review before any use."),
    "MISSING_HUMAN_REVIEW_CAVEAT": ("Include an explicit 'human review is required' caveat."),
    "INVALID_SUPPORT_TIER": (
        "Support tier must reflect universal, targeted, intensive, or enrichment framing."
    ),
    "MISSING_PROGRESS_MONITORING": ("Add at least one progress-monitoring measure."),
    "MISSING_NEXT_STEPS": ("Add at least one educator next step."),
    "MISSING_RATIONALE": ("Provide a non-empty rationale grounded in the analyst evidence."),
    "CONTRACT_VERSION_MISMATCH": ("Set contract_version to the required value."),
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
