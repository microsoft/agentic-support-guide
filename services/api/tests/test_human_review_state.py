from __future__ import annotations

import pytest

from app.human_review import (
    HumanReviewState,
    InvalidReviewTransitionError,
    ReviewTransitionAuditEntry,
    can_transition,
    transition,
)


def test_allowed_transitions() -> None:
    assert can_transition(HumanReviewState.DRAFT, HumanReviewState.PENDING_REVIEW)
    assert can_transition(HumanReviewState.PENDING_REVIEW, HumanReviewState.APPROVED)
    assert can_transition(HumanReviewState.PENDING_REVIEW, HumanReviewState.REJECTED)
    assert can_transition(HumanReviewState.REJECTED, HumanReviewState.PENDING_REVIEW)


def test_disallowed_transitions() -> None:
    assert not can_transition(HumanReviewState.APPROVED, HumanReviewState.DRAFT)
    assert not can_transition(HumanReviewState.APPROVED, HumanReviewState.REJECTED)
    assert not can_transition(HumanReviewState.DRAFT, HumanReviewState.APPROVED)


def test_transition_raises_on_illegal() -> None:
    with pytest.raises(InvalidReviewTransitionError):
        transition(HumanReviewState.APPROVED, HumanReviewState.DRAFT)


def test_audit_entry_contains_only_safe_metadata() -> None:
    entry = ReviewTransitionAuditEntry(
        correlation_id="corr-1",
        dealer_group_id="GROUP-DEMO",
        user_label="Staff S-01",
        timestamp="2026-01-05T09:00:00Z",
        previous_state="pending_review",
        new_state="approved",
        validator_verdict="passed",
        evidence_count=2,
    )
    payload = entry.__dict__
    text = str(payload).lower()
    for forbidden in ("prompt", "completion", "concern_text", "raw_critique", "secret", "token"):
        assert forbidden not in text


def test_review_endpoint_round_trip(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client(demo_reset_enabled=False)
    # First generate a real plan.
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "dealer_group_id": "GROUP-DEMO",
        },
    ).json()
    assert rec["status"] == "ok", rec
    saved = client.post(
        "/api/supports/plans",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "selected_goal": "GOAL-lead-response-1",
            "selected_strategies": ["ST-lead-response-1"],
            "recommendation": rec["recommendation"],
            "dealer_group_id": "GROUP-DEMO",
        },
    ).json()
    plan_id = saved["plan_id"]
    assert saved["human_review_state"] == "pending_review"

    approved = client.post(
        f"/api/supports/plans/{plan_id}/review",
        json={"to_state": "approved", "user_label": "Staff S-01"},
    ).json()
    assert approved["human_review_state"] == "approved"

    # Illegal transition returns 409.
    bad = client.post(
        f"/api/supports/plans/{plan_id}/review",
        json={"to_state": "rejected", "user_label": "Staff S-01"},
    )
    assert bad.status_code == 409
