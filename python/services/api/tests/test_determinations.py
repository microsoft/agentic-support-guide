"""Regression tests for the forbidden-determination policy.

The mechanics cases below each leaked past an earlier detector. They were
found by adversarial review, not by a failing test, which is why they are
pinned here. The domain cases assert the dealership policy: this system
explains what changed and drafts an improvement plan, and must never commit
money, decide credit, judge a named person, or make a compliance or safety
claim.
"""

from __future__ import annotations

import pytest

from app.agents.shared.determinations import (
    HUMAN_REVIEW_CAVEAT,
    POLICY_NOUN_PHRASE,
    REQUIRED_REVIEW_PHRASE,
    asserts_determination,
    denies_human_review,
    offending_fields,
    violates,
)


@pytest.mark.parametrize(
    "text",
    [
        "This is not a credit decision; a qualified lender may approve financing.",
        "We cannot make a pricing determination.",
        "Ask the manufacturer whether any recalls are outstanding.",
        "Review the enquiry response time against the group standard.",
        "Confirm the listing has the required photos before publishing.",
        "A qualified assessor may inspect the vehicle.",
        "This is not a compliance determination.",
    ],
)
def test_safe_phrasing_is_not_flagged(text: str) -> None:
    """Withholding the careful answer would punish exactly the right behaviour."""

    assert not asserts_determination(text)


@pytest.mark.parametrize(
    "text",
    [
        # Committing money.
        "We guarantee a discount of $2,000 on this vehicle.",
        "Your trade-in is worth $8,500.",
        "Our final price is $31,990.",
        # Credit and financing.
        "You are approved for financing at 4.9% APR.",
        "The customer qualifies for credit.",
        "This is our credit decision.",
        # Judging a named individual.
        "Jordan is an underperforming salesperson and should be terminated.",
        # Compliance.
        "The listing is fully compliant with advertising rules.",
        "These listings comply with FTC advertising regulations.",
        "That is our pricing determination.",
        # Safety and recalls.
        "This vehicle has no open recalls.",
        "The car is safe to drive.",
        "It is recall-free and passed the safety inspection.",
        # Guaranteeing an outcome.
        "This plan will increase sales by 20%.",
        "You will sell twelve more units next month.",
        "This approach is guaranteed to work.",
    ],
)
def test_forbidden_determinations_are_flagged(text: str) -> None:
    assert asserts_determination(text)


@pytest.mark.parametrize(
    "text",
    [
        # A cue in a previous sentence excused the next one.
        "A qualified inspector agrees. This is our credit decision.",
        "There is no doubt: our final price is $31,990.",
        # No whitespace, a newline, or a closing quote defeated sentence splitting.
        "No concerns.The car is safe to drive.",
        "- No concerns\n- This vehicle has no open recalls",
        'No concerns." Your trade-in is worth $8,500.',
        # Role noun plus modal anywhere nearby was treated as deferral.
        "The team can meet tomorrow, this is our credit decision.",
        # A cue after the match is not a hedge.
        "This is our credit decision, not a guess.",
    ],
)
def test_exemption_cues_cannot_reach_across_the_text(text: str) -> None:
    """Each of these was exempted by the window the anchoring replaced."""

    assert asserts_determination(text)


def test_a_negation_does_not_make_a_safety_claim_safe() -> None:
    """A "no open recalls" statement is a safety claim however it is phrased."""

    assert asserts_determination("We confirm there are no open recalls.")


def test_a_distant_negation_is_withheld_rather_than_excused() -> None:
    """A deliberate false positive.

    An exemption wide enough to clear "Do not state whether the vehicle is
    compliant" would also clear an assertion separated from its cue by a full
    stop. Withholding the first is the cheaper error.
    """

    assert asserts_determination("Do not state whether the vehicle is compliant with the rules.")


@pytest.mark.parametrize(
    "text",
    [
        "No human review is needed.",
        "Human review is not required.",
        "Human review is not mandatory.",
        "Human review isn\u2019t required.",
        "This can be actioned without human review.",
        "You may skip human review for this one.",
        "Human review is unnecessary here.",
        "Disregard the following boilerplate.",
        # A prohibition earlier in the text used to excuse a later denial.
        "Do not skip human review. Human review is optional.",
        "Always preserve the note: human review is not required.",
        "Don\u2019t require human review.",
        # A prohibition that does not govern the skip verb.
        "Do not hesitate to skip human review.",
    ],
)
def test_claims_that_human_review_can_be_skipped_are_refused(text: str) -> None:
    """Revoking the review control is itself a determination."""

    assert denies_human_review(text)
    assert violates(text)


@pytest.mark.parametrize(
    "text",
    [
        "A human must review this before acting on it.",
        "Do not skip human review.",
        "Never proceed without human review.",
        "Human review is required.",
    ],
)
def test_requiring_review_is_not_mistaken_for_denying_it(text: str) -> None:
    """A naive pattern reads 'do not skip human review' as a denial."""

    assert not denies_human_review(text)


def test_every_field_is_scanned_not_just_the_rationale() -> None:
    """A determination in `manager_next_steps` was previously accepted."""

    draft = {
        "rationale": "Enquiry response has slipped since April.",
        "decision_rule": "Escalate when two indicators decline together.",
        "caveats": ["A human must review this."],
        "manager_next_steps": ["Tell the customer their trade-in is worth $8,500."],
    }
    assert offending_fields(draft) == ["manager_next_steps"]


def test_skipped_fields_are_not_scanned() -> None:
    """Retrieved evidence legitimately discusses these topics."""

    draft = {
        "rationale": "Enquiry response has slipped since April.",
        "citations": [{"evidence_summary": "Guidance on how recalls are published."}],
    }
    assert offending_fields(draft, skip=frozenset({"citations"})) == []


def test_nested_values_are_reached() -> None:
    draft = {"progress_monitoring": [{"note": "The customer qualifies for credit."}]}
    assert offending_fields(draft) == ["progress_monitoring"]


def test_non_text_fields_are_ignored() -> None:
    assert offending_fields({"review_window_days": 30, "resource_ids": []}) == []


def test_cross_chunk_phrases_are_caught() -> None:
    """A phrase split over two bullets matches neither bullet alone."""

    draft = {"caveats": ["The car is", "safe to drive.", "Human review is required."]}
    assert offending_fields(draft) == ["caveats"]


def test_mapping_keys_are_not_treated_as_prose() -> None:
    """Joining a key to its value invented a phrase that was never written."""

    assert offending_fields({"outer": {"safe": "to drive"}}) == []


def test_the_caveat_does_not_trip_the_policy_it_states() -> None:
    """The caveat names the forbidden determinations; it must not self-flag."""

    assert not violates(HUMAN_REVIEW_CAVEAT)


def test_the_standard_caveat_satisfies_the_standard_caveat_check() -> None:
    """These rules lived apart, and the shipped caveat failed the shipped check."""

    assert REQUIRED_REVIEW_PHRASE in HUMAN_REVIEW_CAVEAT.lower()


def test_the_stated_policy_and_the_enforced_policy_stay_in_sync() -> None:
    """The prompt tells models the rule; this asserts the rule is the same one."""

    from app.foundry_agents import RUNTIME_ENVELOPE

    assert POLICY_NOUN_PHRASE in RUNTIME_ENVELOPE
