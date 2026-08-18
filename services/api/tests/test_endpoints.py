from __future__ import annotations

from .conftest import make_default_client


def test_health_reports_provider_status() -> None:
    client = make_default_client()
    body = client.get("/api/health").json()
    assert body["service"] == "agentic-support-guide-api"
    assert body["auth_mode"] == "entra"
    assert body["provider_configured"] is False
    assert "mock_mode" not in body


def test_dashboard_summary_shape() -> None:
    client = make_default_client()
    body = client.get("/api/dashboard/summary").json()
    assert len(body["kpi_cards"]) == 4
    assert body["proficiency_trend"]
    assert body["domain_distribution"]


def test_assessments_summary_shape() -> None:
    client = make_default_client()
    body = client.get("/api/assessments/summary").json()
    assert body["generated_by"].startswith("Generated from local rules")


def test_behavior_and_learners() -> None:
    client = make_default_client()
    behavior = client.get("/api/behavior/summary").json()
    assert behavior["total_records"] == 150
    learners = client.get("/api/learners").json()
    assert learners["total"] == 120


def test_supports_options_lists_categories_and_learners() -> None:
    client = make_default_client()
    body = client.get("/api/supports/options").json()
    assert len(body["learners"]) == 120
    assert body["categories"]


def test_openapi_served_under_api_prefix() -> None:
    client = make_default_client()
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "Agentic Support Guide API"


def test_recommendation_endpoint_returns_envelope_and_appends_audit() -> None:
    client = make_default_client()
    before_audit = client.get("/api/audit/events").json()["total"]

    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
        },
    )
    body = resp.json()
    assert body["status"] == "ok"
    assert body["recommendation"] is not None
    assert "mock_mode" not in body
    assert body["provider_model"].startswith("mock")
    assert len(body["agent_trace"]) == 3

    after_audit = client.get("/api/audit/events").json()["total"]
    assert after_audit == before_audit + 1


def test_save_plan_persists_across_requests() -> None:
    client = make_default_client()
    initial = client.get("/api/supports/plans").json()["total"]

    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
        },
    ).json()["recommendation"]

    saved = client.post(
        "/api/supports/plans",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "selected_smart_goal": "SG-early-literacy-1",
            "selected_strategies": ["ST-early-literacy-1"],
            "recommendation": rec,
        },
    ).json()
    assert saved["plan_id"].startswith("PLN-")

    after = client.get("/api/supports/plans").json()
    assert after["total"] == initial + 1


def test_unknown_learner_returns_404() -> None:
    client = make_default_client()
    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-9999",
            "category": "early-literacy",
            "concern_text": "test",
        },
    )
    assert resp.status_code == 404
