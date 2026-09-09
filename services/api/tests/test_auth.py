"""Authentication and district authorization.

Before this existed, any caller chose their own `district_id` in the request
body, so district scoping was a suggestion. Retrieval-layer filtering cannot
fix that: it faithfully returns whichever district the caller asked for.

These tests send real Easy Auth principal headers rather than disabling
auth, so the header parsing and authorization path actually runs.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from .conftest import TEST_PRINCIPAL_OID, make_default_client, principal_header

OTHER_OID = "99999999-9999-9999-9999-999999999999"

RECOMMENDATION_BODY = {
    "district_id": "DIST-A",
    "learner_id": "LRN-0001",
    "category": "early-literacy",
    "concern_text": "Letter-sound fluency below expected pace.",
}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    c = make_default_client()
    yield c
    c.close()


def _restrict_to(districts: str, *, facilitator: bool = False) -> None:
    os.environ["DISTRICT_ASSIGNMENTS"] = f"{TEST_PRINCIPAL_OID}={districts}"
    os.environ["FACILITATOR_OBJECT_IDS"] = TEST_PRINCIPAL_OID if facilitator else ""


# --- authentication ---------------------------------------------------


def test_request_without_principal_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations/support-plan",
        json=RECOMMENDATION_BODY,
        headers={"x-ms-client-principal": ""},
    )
    assert response.status_code == 401


def test_malformed_principal_header_is_rejected(client: TestClient) -> None:
    response = client.get("/api/me", headers={"x-ms-client-principal": "not-base64!!"})
    assert response.status_code == 401


def test_principal_without_object_id_is_rejected(client: TestClient) -> None:
    payload = {"auth_typ": "aad", "claims": [{"typ": "name", "val": "No Oid"}]}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    response = client.get("/api/me", headers={"x-ms-client-principal": encoded})
    assert response.status_code == 401


def test_health_stays_anonymous(client: TestClient) -> None:
    """deploy-app.ps1 polls health to detect stale builds before login exists."""

    response = client.get("/api/health", headers={"x-ms-client-principal": ""})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- authorization ----------------------------------------------------


def test_unassigned_identity_gets_no_districts(client: TestClient) -> None:
    """An unknown caller must get nothing, never a default district."""

    os.environ["DISTRICT_ASSIGNMENTS"] = ""
    os.environ["FACILITATOR_OBJECT_IDS"] = ""
    response = client.get("/api/me", headers=principal_header(object_id=OTHER_OID))
    assert response.status_code == 200
    body = response.json()
    assert body["districts"] == []
    assert body["is_facilitator"] is False


def test_recommendation_for_unassigned_district_is_forbidden(client: TestClient) -> None:
    """This is the endpoint that spends model quota, so it must fail first."""

    _restrict_to("DIST-B")
    response = client.post("/api/recommendations/support-plan", json=RECOMMENDATION_BODY)
    assert response.status_code == 403


def test_recommendation_for_assigned_district_is_allowed(client: TestClient) -> None:
    _restrict_to("DIST-A")
    response = client.post("/api/recommendations/support-plan", json=RECOMMENDATION_BODY)
    assert response.status_code == 200


def test_saving_a_plan_for_another_district_is_forbidden(client: TestClient) -> None:
    # Build a fully valid save request while authorized, so the only thing
    # that changes between allowed and denied is the caller's assignment.
    _restrict_to("DIST-A|DIST-B|DIST-DEMO", facilitator=True)
    recommendation = client.post(
        "/api/recommendations/support-plan",
        json={
            "learner_id": "LRN-0001",
            "category": "early-literacy",
            "concern_text": "Letter-sound fluency below expected pace.",
            "district_id": "DIST-DEMO",
        },
    ).json()["recommendation"]

    save_body = {
        "learner_id": "LRN-0001",
        "district_id": "DIST-DEMO",
        "category": "early-literacy",
        "concern_text": "Letter-sound fluency below expected pace.",
        "selected_smart_goal": "SG-early-literacy-1",
        "selected_strategies": ["ST-early-literacy-1"],
        "recommendation": recommendation,
    }
    assert client.post("/api/supports/plans", json=save_body).status_code == 200

    _restrict_to("DIST-B")
    assert client.post("/api/supports/plans", json=save_body).status_code == 403


def test_saved_plans_are_filtered_to_the_callers_districts(client: TestClient) -> None:
    _restrict_to("DIST-A|DIST-B|DIST-DEMO", facilitator=True)
    everything = client.get("/api/supports/plans").json()["plans"]
    districts_present = {p["district_id"] for p in everything}

    _restrict_to("DIST-A")
    scoped = client.get("/api/supports/plans").json()["plans"]
    scoped_districts = {p["district_id"] for p in scoped}

    assert scoped_districts <= {"DIST-A"}
    if districts_present - {"DIST-A"}:
        assert len(scoped) < len(everything), "filtering had no effect"


def test_audit_events_are_filtered_to_the_callers_districts(client: TestClient) -> None:
    _restrict_to("DIST-A")
    rows = client.get("/api/audit/events").json()["events"]
    assert all(r.get("district_id") in ("DIST-A", "", None) for r in rows)


def test_demo_reset_is_facilitator_only() -> None:
    c = make_default_client(demo_reset_enabled=True)
    try:
        _restrict_to("DIST-A", facilitator=False)
        assert c.post("/api/demo/reset").status_code == 403

        _restrict_to("DIST-A", facilitator=True)
        assert c.post("/api/demo/reset").status_code == 200
    finally:
        c.close()
