from __future__ import annotations

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


def test_supports_options() -> None:
    client = make_default_client()
    body = client.get("/api/supports/options").json()
    assert len(body["learners"]) == 120


def test_openapi() -> None:
    client = make_default_client()
    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "Agentic Support Guide API"


def test_recommendation_envelope_carries_correlation_and_district() -> None:
    client = make_default_client()
    before_audit = client.get("/api/audit/events").json()["total"]

    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "district_id": "DIST-DEMO",
        },
    )
    body = resp.json()
    assert body["status"] == "ok"
    assert body["district_id"] == "DIST-DEMO"
    assert body["correlation_id"]
    assert body["recommendation"] is not None
    assert body["recommendation"]["district_id"] == "DIST-DEMO"
    assert body["recommendation"]["human_review_state"] == "pending_review"
    assert body["recommendation"]["citations"]
    for c in body["recommendation"]["citations"]:
        assert c["district_id"] == "DIST-DEMO"
    assert len(body["agent_trace"]) == 4

    after_audit = client.get("/api/audit/events").json()["total"]
    assert after_audit == before_audit + 1

    # Verify the runtime audit row carries the safe metadata fields.
    events = client.get("/api/audit/events").json()["events"]
    last = events[-1]
    assert last["correlation_id"] == body["correlation_id"]
    assert last["district_id"] == "DIST-DEMO"
    assert last["evidence_count"] >= 1
    assert last["citation_count"] >= 1
    assert last["validator_status"]


def test_save_plan_persists_district_and_review_state() -> None:
    client = make_default_client()
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "district_id": "DIST-DEMO",
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
            "district_id": "DIST-DEMO",
        },
    ).json()
    assert saved["district_id"] == "DIST-DEMO"
    assert saved["human_review_state"] == "pending_review"


def test_save_plan_rejects_recommendation_from_another_district() -> None:
    """The save endpoint does not re-run the pipeline, so it must re-check."""

    client = make_default_client()
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "district_id": "DIST-DEMO",
        },
    ).json()["recommendation"]

    resp = client.post(
        "/api/supports/plans",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "selected_smart_goal": None,
            "selected_strategies": [],
            "recommendation": rec,
            "district_id": "DIST-A",
        },
    )
    assert resp.status_code == 422


def test_save_plan_rejects_oversized_rationale() -> None:
    client = make_default_client()
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "district_id": "DIST-DEMO",
        },
    ).json()["recommendation"]
    rec["rationale"] = "x" * 5000

    resp = client.post(
        "/api/supports/plans",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "selected_smart_goal": None,
            "selected_strategies": [],
            "recommendation": rec,
            "district_id": "DIST-DEMO",
        },
    )
    assert resp.status_code == 422


def test_unknown_learner_returns_404() -> None:
    client = make_default_client()
    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-9999",
            "category": "early-literacy",
            "concern_text": "test",
            "district_id": "DIST-DEMO",
        },
    )
    assert resp.status_code == 404


def test_missing_district_id_rejected_with_422() -> None:
    client = make_default_client()
    resp = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "test",
        },
    )
    assert resp.status_code == 422
