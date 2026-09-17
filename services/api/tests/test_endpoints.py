from __future__ import annotations

from app.config import COUNTS

from .conftest import make_default_client


def test_health_reports_provider_status() -> None:
    client = make_default_client()
    body = client.get("/api/health").json()
    assert body["service"] == "agentic-support-guide-api"
    assert body["foundry_auth_mode"] == "entra"
    assert body["provider_configured"] is True


def test_dashboard_summary_shape() -> None:
    client = make_default_client()
    body = client.get("/api/dashboard/summary").json()
    assert len(body["kpi_cards"]) == 4


def test_scores_summary_shape() -> None:
    client = make_default_client()
    body = client.get("/api/scores/summary").json()
    assert body["generated_by"].startswith("Generated from local rules")


def test_operations_and_dealerships() -> None:
    client = make_default_client()
    behavior = client.get("/api/operations/summary").json()
    assert behavior["total_records"] == COUNTS.dealerships * COUNTS.score_periods
    dealerships = client.get("/api/dealerships").json()
    assert dealerships["total"] == 120


def test_supports_options() -> None:
    client = make_default_client()
    body = client.get("/api/supports/options").json()
    assert len(body["dealerships"]) == 120


def test_openapi() -> None:
    client = make_default_client()
    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "Agentic Support Guide API"


def test_recommendation_envelope_carries_correlation_and_dealer_group() -> None:
    client = make_default_client()
    before_audit = client.get("/api/audit/events").json()["total"]

    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "dealer_group_id": "GROUP-DEMO",
        },
    )
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dealer_group_id"] == "GROUP-DEMO"
    assert body["correlation_id"]
    assert body["recommendation"] is not None
    assert body["recommendation"]["dealer_group_id"] == "GROUP-DEMO"
    assert body["recommendation"]["human_review_state"] == "pending_review"
    assert body["recommendation"]["citations"]
    for c in body["recommendation"]["citations"]:
        assert c["dealer_group_id"] == "GROUP-DEMO"
    assert len(body["agent_trace"]) == 4

    after_audit = client.get("/api/audit/events").json()["total"]
    assert after_audit == before_audit + 1

    # Verify the runtime audit row carries the safe metadata fields.
    events = client.get("/api/audit/events").json()["events"]
    last = events[-1]
    assert last["correlation_id"] == body["correlation_id"]
    assert last["dealer_group_id"] == "GROUP-DEMO"
    assert last["evidence_count"] >= 1
    assert last["citation_count"] >= 1
    assert last["validator_status"]


def test_save_plan_persists_dealer_group_and_review_state() -> None:
    client = make_default_client()
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "dealer_group_id": "GROUP-DEMO",
        },
    ).json()["recommendation"]

    saved = client.post(
        "/api/supports/plans",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "selected_goal": "GOAL-lead-response-1",
            "selected_strategies": ["ST-lead-response-1"],
            "recommendation": rec,
            "dealer_group_id": "GROUP-DEMO",
        },
    ).json()
    assert saved["dealer_group_id"] == "GROUP-DEMO"
    assert saved["human_review_state"] == "pending_review"


def test_save_plan_rejects_recommendation_from_another_dealer_group() -> None:
    """The save endpoint does not re-run the pipeline, so it must re-check."""

    client = make_default_client()
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "dealer_group_id": "GROUP-DEMO",
        },
    ).json()["recommendation"]

    resp = client.post(
        "/api/supports/plans",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "selected_goal": None,
            "selected_strategies": [],
            "recommendation": rec,
            "dealer_group_id": "GROUP-A",
        },
    )
    assert resp.status_code == 422


def test_save_plan_rejects_oversized_rationale() -> None:
    client = make_default_client()
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "dealer_group_id": "GROUP-DEMO",
        },
    ).json()["recommendation"]
    rec["rationale"] = "x" * 5000

    resp = client.post(
        "/api/supports/plans",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "Median first response to online enquiries slipped past one hour.",
            "selected_goal": None,
            "selected_strategies": [],
            "recommendation": rec,
            "dealer_group_id": "GROUP-DEMO",
        },
    )
    assert resp.status_code == 422


def test_unknown_dealership_returns_404() -> None:
    client = make_default_client()
    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-9999",
            "category": "lead-response",
            "concern_text": "test",
            "dealer_group_id": "GROUP-DEMO",
        },
    )
    assert resp.status_code == 404


def test_missing_dealer_group_id_rejected_with_422() -> None:
    client = make_default_client()
    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "dealership_id": "DLR-0001",
            "category": "lead-response",
            "concern_text": "test",
        },
    )
    assert resp.status_code == 422
