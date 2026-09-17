"""The deterministic validator checks.

Each check is an independent function that records findings; `run_checks`
applies all of them. Adding a rule means adding a function and listing it in
`DETERMINISTIC_CHECKS` -- no existing check has to be edited.

These decide pass/fail. The LLM critique in `agent.py` is advisory and can
only add warning codes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..shared.determinations import (
    REQUIRED_REVIEW_PHRASE,
    denies_human_review,
    offending_fields,
)
from .context import ValidatorInput

REQUIRED_KEYWORD_CAVEATS = (REQUIRED_REVIEW_PHRASE,)
REQUIRED_TIER_PATTERNS = ("baseline", "focused", "intensive", "advanced")

# Identifiers carry no prose. Citations are retrieved evidence rather than
# something this system asserts, and source material legitimately discusses
# recalls and pricing rules, so scanning them would fail honest answers.
#
# Residual risk, accepted: a poisoned source document carrying the requesting
# dealer_group_id could put a determination on screen inside a citation. It is
# bounded because the model cannot author citation text -- the recommender
# substitutes the retriever's stored Citation -- and because each learner owns
# their own index. Citations are still screened for review denial below.
DETERMINATION_SCAN_SKIP = frozenset({"contract_version", "dealer_group_id", "citations"})


@dataclass
class Findings:
    """What the checks found, in the shape the report needs.

    Codes and fields are de-duplicated when the report is built, so a check
    never has to ask whether an earlier check already flagged something.
    """

    issue_codes: list[str] = field(default_factory=list)
    failed_fields: list[str] = field(default_factory=list)
    # Carried separately because the repair guidance names the offending ids.
    unknown_resource_ids: list[str] = field(default_factory=list)

    def flag(self, code: str, *fields: str) -> None:
        self.issue_codes.append(code)
        self.failed_fields.extend(fields)

    @property
    def passed(self) -> bool:
        return not self.issue_codes


def check_contract_version(payload: ValidatorInput, findings: Findings) -> None:
    required = payload.context.required_contract_version
    if payload.draft.contract_version != required:
        findings.flag("CONTRACT_VERSION_MISMATCH", "contract_version")
    if payload.analysis.contract_version != required:
        findings.flag("CONTRACT_VERSION_MISMATCH")


def check_dealer_group(payload: ValidatorInput, findings: Findings) -> None:
    if payload.draft.dealer_group_id != payload.context.dealer_group_id:
        findings.flag("DRAFT_DEALER_GROUP_MISMATCH", "dealer_group_id")


def check_catalog_membership(payload: ValidatorInput, findings: Findings) -> None:
    """The draft may only reference ids the API handed the recommender."""

    allowed_resources = set(payload.context.allowed_resource_ids)
    unknown = [rid for rid in payload.draft.resource_ids if rid not in allowed_resources]
    if unknown:
        findings.unknown_resource_ids.extend(unknown)
        findings.flag("UNKNOWN_RESOURCE_ID", "resource_ids")

    allowed_goals = set(payload.context.allowed_goal_ids)
    if any(gid not in allowed_goals for gid in payload.draft.goal_suggestions):
        findings.flag("UNKNOWN_GOAL_ID", "goal_suggestions")

    allowed_strategies = set(payload.context.allowed_strategy_ids)
    if any(sid not in allowed_strategies for sid in payload.draft.strategy_suggestions):
        findings.flag("UNKNOWN_STRATEGY_ID", "strategy_suggestions")


def check_citations(payload: ValidatorInput, findings: Findings) -> None:
    """The core evidence-backed requirement."""

    if not payload.draft.citations:
        findings.flag("MISSING_CITATIONS", "citations")
        return

    allowed = set(payload.context.allowed_citation_ids)
    for citation in payload.draft.citations:
        if citation.dealer_group_id != payload.context.dealer_group_id:
            findings.flag("CROSS_DEALER_GROUP_CITATION", "citations")
        if citation.citation_id not in allowed:
            findings.flag("UNKNOWN_CITATION_ID", "citations")


def check_caveats(payload: ValidatorInput, findings: Findings) -> None:
    if not payload.draft.caveats:
        findings.flag("MISSING_CAVEATS", "caveats")
        return
    caveat_text = " ".join(payload.draft.caveats).lower()
    if not all(keyword in caveat_text for keyword in REQUIRED_KEYWORD_CAVEATS):
        findings.flag("MISSING_HUMAN_REVIEW_CAVEAT", "caveats")


def check_support_tier(payload: ValidatorInput, findings: Findings) -> None:
    tier = payload.draft.support_tier.lower()
    if not any(pattern in tier for pattern in REQUIRED_TIER_PATTERNS):
        findings.flag("INVALID_SUPPORT_TIER", "support_tier")


def check_required_sections(payload: ValidatorInput, findings: Findings) -> None:
    if not payload.draft.progress_monitoring:
        findings.flag("MISSING_PROGRESS_MONITORING", "progress_monitoring")
    if not payload.draft.manager_next_steps:
        findings.flag("MISSING_NEXT_STEPS", "manager_next_steps")
    if not payload.draft.rationale.strip():
        findings.flag("MISSING_RATIONALE", "rationale")


def check_forbidden_determinations(payload: ValidatorInput, findings: Findings) -> None:
    """Scans every draft field, not a chosen three."""

    offenders = offending_fields(payload.draft.model_dump(), skip=DETERMINATION_SCAN_SKIP)
    # The analyst's summary is not part of the draft, but the coordinator
    # serves `detected_need` and `evidence_summary` straight from it. Left
    # unscanned, a determination there reached the UI with completeness ok.
    offenders += [
        f"analysis.{name}" for name in offending_fields(payload.analysis.analysis.model_dump())
    ]
    if offenders:
        findings.flag("FORBIDDEN_DETERMINATION", *offenders)

    # Citation text is retrieved evidence, so it is not scanned for
    # determinations -- source material discusses them legitimately. A source
    # claiming review can be skipped is never legitimate, though, and that is
    # the shape a poisoned document would take.
    if any(denies_human_review(c.evidence_summary) for c in payload.draft.citations):
        findings.flag("FORBIDDEN_DETERMINATION", "citations")


DETERMINISTIC_CHECKS: tuple[Callable[[ValidatorInput, Findings], None], ...] = (
    check_contract_version,
    check_dealer_group,
    check_catalog_membership,
    check_citations,
    check_caveats,
    check_support_tier,
    check_required_sections,
    check_forbidden_determinations,
)


def run_checks(payload: ValidatorInput) -> Findings:
    """Run every check. None of them short-circuit.

    A draft that fails one rule is still measured against the rest, so a
    single repair round can address everything at once.
    """

    findings = Findings()
    for check in DETERMINISTIC_CHECKS:
        check(payload, findings)
    return findings
