"""Forbidden-determination policy.

One definition enforced in four places: the validator agent, the hosted
agent's output gate, the prompt envelope every model receives, and the
offline eval gate. Each of those used to carry its own phrase list and they
had already drifted apart.

This is a denylist, and denylists leak — Module 8 measures exactly that. What
this module owes the rest of the system is that it fails *closed*: an
exemption has to be earned by a construction sitting immediately next to the
match, never by a keyword loose in the surrounding text.

Bundled flat into the hosted agent's zip, so this module must stay
stdlib-only and must not import from the app package.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

# Prose injected into prompts and caveats. Tests hold this in sync with the
# patterns below so the instruction and the detector cannot disagree.
POLICY_NOUN_PHRASE = (
    "pricing, financing, credit, compliance, safety, or individual staffing determinations"
)

# The phrase the validator requires to appear in a draft's caveats. The caveat
# below has to contain it: the two rules used to live in different files and
# the standard caveat did not satisfy the standard check.
REQUIRED_REVIEW_PHRASE = "human review"

HUMAN_REVIEW_CAVEAT = (
    "A human must review this before acting on it. This is synthetic guidance "
    "and is not a pricing, financing, credit, compliance, safety, or staffing "
    "determination. Human review is required before use."
)

# Models emit curly apostrophes routinely, and the patterns below are written
# with straight ones. This is typography, not evasion.
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'", "\u2018": "'"})


# The categories named in POLICY_NOUN_PHRASE, so the instruction the models are
# given and the rule enforced here cover the same ground.
_CATEGORIES = r"pricing|price|financing|finance|credit|lending|compliance|legal|safety|staffing"

# `disclaimable` says whether "this is not a X" is a legitimate disclaimer.
# It is, for the *act* ("this is not a credit decision"). It is not for the
# *ruling*: "this vehicle has no open recalls" is a safety claim whichever way
# it is phrased, and negating it does not make it safe to assert.
_RULES: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(rf"\b(?:{_CATEGORIES})\s+determinations?\b", re.IGNORECASE), True),
    # Committing money.
    (
        re.compile(
            r"\b(?:guarantee|guarantees|guaranteed)\s+(?:a\s+|the\s+)?"
            r"(?:price|discount|rate|apr|trade[-\s]?in)\b",
            re.IGNORECASE,
        ),
        True,
    ),
    (re.compile(r"\btrade[-\s]?in\s+is\s+worth\b", re.IGNORECASE), False),
    (re.compile(r"\b(?:final|best|lowest)\s+price\s+(?:is|will\s+be)\b", re.IGNORECASE), False),
    (re.compile(r"\b(?:discount|reduction)\s+of\s+\$", re.IGNORECASE), False),
    (
        re.compile(
            r"\bwe\s+(?:will|can)\s+(?:sell|offer|match|beat)\b[^.!?;]{0,40}\$",
            re.IGNORECASE,
        ),
        False,
    ),
    # Credit and financing decisions.
    (
        re.compile(
            r"\b(?:approved|pre[-\s]?approved|declined|denied)\s+for\s+"
            r"(?:financing|finance|credit|a\s+loan)\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (re.compile(r"\bqualif(?:y|ies|ied)\s+for\s+(?:financing|credit)\b", re.IGNORECASE), False),
    (re.compile(r"\bcredit\s+(?:decision|approval|denial)\b", re.IGNORECASE), True),
    # Judging a named individual rather than the process.
    (
        re.compile(
            r"\b(?:should\s+be\s+)?(?:terminated|dismissed|fired|"
            r"put\s+on\s+a\s+performance\s+plan|disciplined)\b",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(
            r"\b(?:poor|bad|weak|underperforming|incompetent)\s+"
            r"(?:salesperson|sales\s+person|advisor|adviser|employee|manager)\b",
            re.IGNORECASE,
        ),
        False,
    ),
    # Compliance claims.
    (re.compile(r"\b(?:is|are)\s+(?:fully\s+)?compliant\s+with\b", re.IGNORECASE), True),
    (
        re.compile(
            r"\bcompl(?:y|ies|ied)\s+with\b[^.!?;]{0,40}"
            r"\b(?:regulation|regulations|rule|rules|law|laws|ftc|advertising)\b",
            re.IGNORECASE,
        ),
        True,
    ),
    # Safety and recall claims.
    (re.compile(r"\bno\s+open\s+recalls?\b", re.IGNORECASE), False),
    (re.compile(r"\brecall[-\s]free\b", re.IGNORECASE), False),
    (re.compile(r"\bsafe\s+to\s+drive\b", re.IGNORECASE), False),
    (
        re.compile(
            r"\bpassed\s+(?:the\s+)?(?:safety\s+|roadworthiness\s+)?inspection\b",
            re.IGNORECASE,
        ),
        False,
    ),
    # Guaranteeing a commercial outcome.
    (
        re.compile(
            r"\b(?:will|shall)\s+(?:increase|grow|improve|lift|boost)\b[^.!?;]{0,20}\bsales\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (re.compile(r"\byou\s+will\s+sell\b", re.IGNORECASE), False),
    (re.compile(r"\bguaranteed\s+to\s+\w+", re.IGNORECASE), True),
)

# Every exemption is anchored with `$` against the text immediately preceding
# the match. That anchoring is what replaced sentence splitting: a cue two
# sentences away, across a newline, or after an abbreviation like "Dr." can no
# longer reach the match, and no window length has to be guessed.
_DISCLAIMER = re.compile(
    r"(?:\b(?:is|are|was|were|am)\s+not\s+(?:a|an|the)?\s*"
    r"|\b(?:isn't|aren't|wasn't|weren't)\s+(?:a|an|the)?\s*"
    # A disclaimer may list the categories it denies, as the caveat itself
    # does: "is not a pricing, financing, credit, compliance, safety,
    # determination". Without this the caveat flags its own policy.
    r"|\b(?:is|are|was|were|am)\s+not\s+(?:a|an|the)\s+(?:[a-z]+,\s*)+(?:or\s+)?"
    r"|\bnot\s+(?:a|an|the)\s*"
    r"|\bno\s+"
    r"|\bnever\s+(?:a|an|the)?\s*"
    r"|\b(?:cannot|can't|do\s+not|don't|does\s+not|doesn't|must\s+not)\s+"
    r"(?:make|provide|offer|give|issue|constitute)\s+(?:a|an|the)?\s*"
    r")$",
    re.IGNORECASE,
)

# Deferral to a human decision-maker, e.g. "a qualified inspector may
# determine". `will` is deliberately absent: it predicts rather than defers.
# The role list is a deliberate superset; an unmatched role simply never
# grants an exemption.
_DEFERRAL_BEFORE = re.compile(
    r"\b(?:a|an|the)?\s*(?:qualified|licensed|certified|independent|trained)?\s*"
    r"(?:clinician|specialist|professional|psychologist|physician|doctor|"
    r"evaluator|assessor|inspector|reviewer|expert)s?\s+"
    r"(?:may|might|can|could|would|should)\s+$",
    re.IGNORECASE,
)

# "A credit decision must be left to the finance office." - the deferral follows.
_DEFERRAL_AFTER = re.compile(
    r"^\s*(?:must|should|can|could|may|has\s+to)\s+(?:only\s+)?be\s+"
    r"(?:left|made|given|provided|determined|decided)\s+(?:to|by)\b",
    re.IGNORECASE,
)


def _is_exempt(text: str, match: re.Match[str], *, disclaimable: bool) -> bool:
    before = text[: match.start()]
    after = text[match.end() :]
    if _DEFERRAL_BEFORE.search(before) or _DEFERRAL_AFTER.match(after):
        return True
    return disclaimable and bool(_DISCLAIMER.search(before))


def asserts_determination(text: str) -> bool:
    """True only for assertions, so refusals and deferrals are not withheld."""

    if not text:
        return False
    folded = text.translate(_APOSTROPHES)
    for pattern, disclaimable in _RULES:
        for match in pattern.finditer(folded):
            if not _is_exempt(folded, match, disclaimable=disclaimable):
                return True
    return False


# A claim that human review can be skipped is itself a determination: it
# revokes the one control every answer depends on.
#
# Two kinds. A *soft* denial names an action ("skip human review") and can be
# legitimate under a prohibition: "do not skip human review" requires review.
# A *hard* denial states the conclusion ("human review is optional"), and no
# preceding word rescues that.
_REVIEW_SKIP_ACTION = re.compile(
    r"\b(?:no|without|skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?|waive[sd]?|"
    r"forgo(?:es|ing)?|omit(?:s|ted|ting)?|disregard(?:s|ed|ing)?|ignore[sd]?)\b"
    r"[^.!?;]{0,40}?\bhuman\s+review\b",
    re.IGNORECASE,
)

_REVIEW_DENIED_OUTRIGHT = re.compile(
    r"\bhuman\s+review\b[^.!?;]{0,40}?"
    r"\b(?:is\s+)?(?:not|isn't|no\s+longer)\s+"
    r"(?:needed|required|necessary|mandatory|expected|important)\b"
    r"|\bhuman\s+review\b[^.!?;]{0,40}?\b(?:unnecessary|optional|redundant)\b"
    r"|\b(?:do\s+not|don't|does\s+not|doesn't|never|must\s+not|should\s+not)\s+"
    r"(?:require|requires|mandate|mandates|need|needs|insist\s+on)\b"
    r"[^.!?;]{0,20}?\bhuman\s+review\b"
    # Telling the reader to ignore the safety text is the same move as removing
    # it, and the caveat says "a human must review" rather than "human review",
    # so the clauses above do not see it.
    r"|\b(?:disregard|ignore|skip|omit)\b[^.!?;]{0,30}?"
    r"\b(?:caveat|caveats|boilerplate|disclaimer|warning|safety\s+notice)\b",
    re.IGNORECASE,
)

# Prohibitions that make a skip *action* mandatory-review language instead.
# Anchored, and allowing at most one intervening word, so the prohibition has
# to govern the skip verb itself: "do not skip" and "never proceed without"
# qualify, while "do not hesitate to skip" does not.
_REVIEW_PROHIBITION = re.compile(
    r"\b(?:do\s+not|don't|does\s+not|doesn't|never|must\s+not|cannot|can't|"
    r"should\s+not|shouldn't)\s+(?:\w+\s+){0,1}$",
    re.IGNORECASE,
)


def denies_human_review(text: str) -> bool:
    """True when the text claims human review can be skipped."""

    if not text:
        return False
    folded = text.translate(_APOSTROPHES)
    if _REVIEW_DENIED_OUTRIGHT.search(folded):
        return True
    # Checked immediately before each match rather than anywhere earlier. A
    # text-wide override let "Do not skip human review. Human review is
    # optional." excuse its own second sentence, and a clause-wide one let
    # "Do not hesitate to skip human review." pass.
    return any(
        not _REVIEW_PROHIBITION.search(folded[: match.start()])
        for match in _REVIEW_SKIP_ACTION.finditer(folded)
    )


def violates(text: str) -> bool:
    """Single predicate for callers that do not care which rule tripped."""

    return asserts_determination(text) or denies_human_review(text)


def _strings(value: object, depth: int = 0) -> Iterable[str]:
    """Yield every string reachable from a payload field.

    Mapping *keys* are deliberately not yielded: they are schema, not prose,
    and joining them with their values manufactured phrases that were never
    in the text (`{"placement": "decision"}`).
    """

    if depth > 6:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item, depth + 1)
    elif isinstance(value, (set, frozenset)) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    ):
        for item in value:
            yield from _strings(item, depth + 1)


def _field_texts(value: object) -> list[str]:
    """The field's own strings, plus the concatenation of list items.

    A phrase split across two bullets ("Our placement" / "decision is final")
    matches neither on its own. The old validator joined caveats before
    scanning and would have caught it, so the join is kept — but only for
    ordered sequences, where adjacency is real.
    """

    parts = list(_strings(value))
    is_sequence = isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    if is_sequence and len(parts) > 1:
        parts.append(" ".join(parts))
    return parts


def offending_fields(
    payload: Mapping[str, object], *, skip: frozenset[str] = frozenset()
) -> list[str]:
    """Names of fields whose free text asserts a forbidden determination.

    Scanning every field is the point. Restricting the scan to `rationale`,
    `decision_rule` and `caveats` meant a diagnosis placed in
    `manager_next_steps` was accepted without comment.
    """

    hits: list[str] = []
    for name, value in payload.items():
        if name in skip:
            continue
        if any(violates(chunk) for chunk in _field_texts(value)):
            hits.append(name)
    return hits
