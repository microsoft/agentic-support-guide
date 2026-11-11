"""Validator Agent.

Deterministic Python checks decide pass/fail; they live in `checks.py`. The
optional remote LLM critique may only add advisory warning codes. Repair
guidance comes from the fixed templates in `repair.py`. Raw model critique
never reaches the UI or the audit trail.

What is checked, in this iteration:

- contract-version match,
- allowed resource / goal / strategy IDs,
- required caveats (including "human review"),
- required support-tier framing,
- required progress-monitoring and next steps,
- rationale is non-empty,
- **at least one citation** on the draft,
- **every citation.dealer_group_id matches the request dealer_group_id**,
- **every citation_id is in the allowed set** produced by the retriever,
- no pricing/credit/compliance/safety/staffing determinations, in **any** draft field.
"""

from __future__ import annotations

import json

from ...foundry_agents.errors import FoundryProviderError
from ...foundry_agents.maf_runtime import MafAgentRuntime
from ..shared.contracts import ValidatorCritiqueModelOutput, ValidatorReport
from ..shared.prompt_blocks import enforce_code, wrap_untrusted
from ..shared.responses import parse_role_response
from .checks import run_checks
from .context import ValidatorContext, ValidatorInput
from .repair import build_repair_guidance, safe_summary

AGENT_ID = "validator"
AGENT_NAME = "validator-agent"

MAX_LLM_WARNINGS = 10

__all__ = ["AGENT_ID", "AGENT_NAME", "ValidatorAgent", "ValidatorContext", "ValidatorInput"]


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
        findings = run_checks(payload)
        issue_codes = sorted(set(findings.issue_codes))
        warning_codes = (
            await self._advisory_warnings(payload, deadline=deadline) if use_llm_critique else []
        )

        return ValidatorReport(
            dealer_group_id=payload.context.dealer_group_id,
            passed=findings.passed,
            issue_codes=issue_codes,
            warning_codes=sorted(set(warning_codes)),
            failed_fields=sorted(set(findings.failed_fields)),
            safe_summary=safe_summary(findings.passed, issue_codes),
            repair_guidance=build_repair_guidance(
                findings.issue_codes, findings.unknown_resource_ids
            ),
        )

    async def _advisory_warnings(
        self, payload: ValidatorInput, *, deadline: float | None
    ) -> list[str]:
        """Critique is a nice-to-have, so no failure here changes the verdict.

        The two failure modes are reported separately: a call that never
        landed is an environment problem, while a call that returned
        unparseable JSON points at the agent definition or the model.
        """

        if not self._runtime.has_role(AGENT_NAME):
            return []
        try:
            return await self._llm_critique(payload, deadline=deadline)
        except FoundryProviderError:
            return ["VALIDATOR_LLM_CRITIQUE_UNAVAILABLE"]
        except Exception:  # noqa: BLE001 - advisory only
            return ["VALIDATOR_LLM_CRITIQUE_UNAVAILABLE"]

    async def _llm_critique(
        self, payload: ValidatorInput, *, deadline: float | None = None
    ) -> list[str]:
        """Returns warning codes only.

        The model's own repair text is deliberately discarded: repair guidance
        shown to a person has to come from `repair.py`.
        """

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
            # Not silence: an off-schema critique means the agent definition
            # or the model drifted, and that is worth seeing in the trace.
            return ["VALIDATOR_LLM_CRITIQUE_UNPARSEABLE"]
        codes = [enforce_code(w) for w in critique.warning_codes if isinstance(w, str)]
        return [code for code in codes if code is not None][:MAX_LLM_WARNINGS]
