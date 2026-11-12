"""Repair guidance and the safe failure summary.

Both are built from fixed templates. Raw model critique never reaches the UI
or the audit trail, so nothing here is model-authored.
"""

from __future__ import annotations

MAX_GUIDANCE_CHARS = 1000
MAX_SUMMARY_CODES = 6

_REPAIR_TEMPLATES = {
    "UNKNOWN_RESOURCE_ID": (
        "Only reference resource ids from the allowed_ids block. Remove any invented ids."
    ),
    "UNKNOWN_GOAL_ID": "Only reference goal ids from the allowed_ids block.",
    "UNKNOWN_STRATEGY_ID": "Only reference strategy ids from the allowed_ids block.",
    "MISSING_CITATIONS": (
        "Cite at least one citation from the group_evidence block. Recommendations without "
        "evidence are rejected."
    ),
    "CROSS_DEALER_GROUP_CITATION": (
        "Every citation.dealer_group_id must match the request dealer_group_id. Remove or replace "
        "any cross-group citations."
    ),
    "UNKNOWN_CITATION_ID": "Only cite citation_ids present in the group_evidence block.",
    "DRAFT_DEALER_GROUP_MISMATCH": (
        "The draft dealer_group_id must match the request dealer_group_id."
    ),
    "MISSING_CAVEATS": "Add caveats that require human review before any use.",
    "MISSING_HUMAN_REVIEW_CAVEAT": "Include an explicit 'human review is required' caveat.",
    "INVALID_SUPPORT_TIER": (
        "Support tier must reflect baseline, focused, intensive, or advanced framing."
    ),
    "MISSING_PROGRESS_MONITORING": "Add at least one progress-monitoring measure.",
    "MISSING_NEXT_STEPS": "Add at least one manager next step.",
    "MISSING_RATIONALE": "Provide a non-empty rationale grounded in the analyst evidence.",
    "CONTRACT_VERSION_MISMATCH": "Set contract_version to the required value.",
    "FORBIDDEN_DETERMINATION": (
        "Remove any pricing, credit, compliance, safety, or individual staffing "
        "determination language."
    ),
}

# A rule lives in two places: the check that emits the code, and the template
# that tells the recommender how to fix it. tests/test_validator_hardening.py
# asserts the two sets agree, because a code with no template silently
# produces repair guidance that omits the very thing that failed.
REPAIRABLE_ISSUE_CODES = frozenset(_REPAIR_TEMPLATES)


def build_repair_guidance(codes: list[str], unknown_resource_ids: list[str]) -> str:
    if not codes:
        return ""
    lines = [
        f"- {_REPAIR_TEMPLATES[code]}" for code in sorted(set(codes)) if code in _REPAIR_TEMPLATES
    ]
    if unknown_resource_ids:
        lines.append(f"- Unknown resource ids: {sorted(unknown_resource_ids)[:5]}")
    return "\n".join(lines)[:MAX_GUIDANCE_CHARS]


def safe_summary(passed: bool, issue_codes: list[str]) -> str:
    """Names the codes only. Never echoes model text or draft content."""

    if passed:
        return "Validator passed all deterministic checks."
    if not issue_codes:
        return "Validator failed with no coded reason."
    joined = ", ".join(issue_codes[:MAX_SUMMARY_CODES])
    if len(issue_codes) > MAX_SUMMARY_CODES:
        joined += f", +{len(issue_codes) - MAX_SUMMARY_CODES} more"
    return f"Validator failed on: {joined}."
