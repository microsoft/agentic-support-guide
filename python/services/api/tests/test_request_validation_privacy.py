"""A rejected request must not echo what was submitted.

FastAPI's default 422 body includes an `input` key holding the offending
value. For this API that value is the user's concern text, so the default
turns a validation error into a disclosure in the response body and in any
log or proxy that records it.
"""

from __future__ import annotations

from .conftest import make_default_client

CANARY = "CANARY-e3f1a9-do-not-echo-this-text"


def test_rejected_request_does_not_echo_submitted_text() -> None:
    client = make_default_client()
    response = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "D-001",
            "category": "service",
            # Over the 1000-character limit, so validation rejects the body.
            "concern_text": CANARY * 60,
            "dealer_group_id": "GROUP-A",
        },
    )

    assert response.status_code == 422
    assert CANARY not in response.text


def test_rejected_request_reports_the_field_that_failed() -> None:
    client = make_default_client()
    response = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "D-001",
            "category": "service",
            "concern_text": "x" * 1001,
            "dealer_group_id": "GROUP-A",
        },
    )

    body = response.json()
    assert body["error_code"] == "REQUEST_VALIDATION_FAILED"
    assert any("concern_text" in field for field in body["fields"])
