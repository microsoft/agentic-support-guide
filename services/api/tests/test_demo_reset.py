from __future__ import annotations

from .conftest import make_default_client


def test_demo_reset_returns_403_when_flag_disabled() -> None:
    client = make_default_client()
    resp = client.post("/api/demo/reset")
    assert resp.status_code == 403
    assert "DEMO_RESET_ENABLED" in resp.json()["detail"]


def test_demo_reset_clears_runtime_state_when_enabled() -> None:
    client = make_default_client(demo_reset_enabled=True)

    # generate a runtime audit row and save a plan
    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
        },
    ).json()
    client.post(
        "/api/supports/plans",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "selected_smart_goal": "SG-early-literacy-1",
            "selected_strategies": ["ST-early-literacy-1"],
            "recommendation": rec["recommendation"],
        },
    )

    plans_before = client.get("/api/supports/plans").json()["total"]
    audit_before = client.get("/api/audit/events").json()["total"]
    assert plans_before > 10  # seeded 10 + one saved
    assert audit_before > 60  # seeded 60 + one runtime row

    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["plans_reset"] == plans_before
    assert body["audit_reset"] == audit_before - 60

    # seeded plans are re-populated; runtime audit is empty
    after_plans = client.get("/api/supports/plans").json()["total"]
    after_audit = client.get("/api/audit/events").json()["total"]
    assert after_plans == 10
    assert after_audit == 60
