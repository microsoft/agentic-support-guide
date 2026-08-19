from __future__ import annotations

from .conftest import make_default_client


def test_demo_reset_returns_403_when_flag_disabled() -> None:
    client = make_default_client()
    resp = client.post("/api/demo/reset")
    assert resp.status_code == 403


def test_demo_reset_clears_runtime_state_when_enabled() -> None:
    client = make_default_client(demo_reset_enabled=True)

    rec = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "district_id": "DIST-DEMO",
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
            "district_id": "DIST-DEMO",
        },
    )

    plans_before = client.get("/api/supports/plans").json()["total"]
    audit_before = client.get("/api/audit/events").json()["total"]
    assert plans_before > 10
    assert audit_before > 60

    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"

    after_plans = client.get("/api/supports/plans").json()["total"]
    after_audit = client.get("/api/audit/events").json()["total"]
    assert after_plans == 10
    assert after_audit == 60
