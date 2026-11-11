"""Human review state model.

Recommendations flow through a small state machine before they are
acted on. This module owns the enum, the allowed transitions, and the
audit-record shape the coordinator emits on each transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HumanReviewState(StrEnum):
    """States a recommendation can be in."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


_ALLOWED_TRANSITIONS: dict[HumanReviewState, frozenset[HumanReviewState]] = {
    HumanReviewState.DRAFT: frozenset({HumanReviewState.PENDING_REVIEW}),
    HumanReviewState.PENDING_REVIEW: frozenset(
        {HumanReviewState.APPROVED, HumanReviewState.REJECTED}
    ),
    HumanReviewState.APPROVED: frozenset(),
    HumanReviewState.REJECTED: frozenset({HumanReviewState.PENDING_REVIEW}),
}


class InvalidReviewTransitionError(ValueError):
    """Raised when caller attempts an illegal state transition."""


def can_transition(from_state: HumanReviewState, to_state: HumanReviewState) -> bool:
    return to_state in _ALLOWED_TRANSITIONS[from_state]


def transition(from_state: HumanReviewState, to_state: HumanReviewState) -> HumanReviewState:
    if not can_transition(from_state, to_state):
        raise InvalidReviewTransitionError(
            f"illegal review transition: {from_state.value} -> {to_state.value}"
        )
    return to_state


@dataclass(frozen=True)
class ReviewTransitionAuditEntry:
    """Safe metadata for a review-state transition audit row.

    Never carries prompts, completions, raw concern text, or secrets.
    """

    correlation_id: str
    dealer_group_id: str
    user_label: str
    timestamp: str
    previous_state: str
    new_state: str
    validator_verdict: str
    evidence_count: int
