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

from app.auth import APP_SERVICE_MARKER, api_auth_mode
from app.districts import KNOWN_DISTRICTS

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


# Reachable without a principal by design: the deploy polls these to find out
# which build is serving, before anyone has signed in. Adding a route here is
# a deliberate act.
ANONYMOUS_PATHS = {"/api/health", "/api/health/details"}


def _requires_principal(dependant: object) -> bool:
    """True when `get_principal` appears anywhere in a route's dependency tree."""

    stack = [dependant]
    while stack:
        current = stack.pop()
        call = getattr(current, "call", None)
        if getattr(call, "__name__", "") == "get_principal":
            return True
        stack.extend(getattr(current, "dependencies", []))
    return False


def test_every_route_requires_a_principal_or_is_explicitly_anonymous() -> None:
    """Catches a new route added without an authorization check.

    Asserted against the dependency tree rather than by calling each endpoint:
    a request with no body returns 422 before authentication, which would make
    an unprotected route look protected.
    """

    from fastapi.routing import APIRoute

    from app.main import create_app

    # Built directly rather than via TestClient.app, which exposes the wrapped
    # ASGI callable. FastAPI stores included routers as `_IncludedRouter`
    # wrappers, so the endpoints are not in `app.routes` and have to be reached
    # through `original_router`.
    app = create_app()
    api_routes: list[APIRoute] = []
    pending: list[object] = list(app.routes)
    while pending:
        entry = pending.pop()
        if isinstance(entry, APIRoute):
            if entry.path.startswith("/api/"):
                api_routes.append(entry)
            continue
        nested = getattr(entry, "original_router", None)
        pending.extend(getattr(nested, "routes", []) or getattr(entry, "routes", []))

    # Without this the test passes silently if route introspection ever breaks.
    assert len(api_routes) >= 12, f"only found {len(api_routes)} routes to check"

    unprotected = sorted(
        f"{sorted(route.methods or [])} {route.path}"
        for route in api_routes
        if route.path not in ANONYMOUS_PATHS and not _requires_principal(route.dependant)
    )
    assert unprotected == [], f"routes missing an authenticated principal: {unprotected}"


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


def test_auth_cannot_be_disabled_on_app_service() -> None:
    """Disabling auth grants facilitator rights over every district.

    Harmless on a laptop, catastrophic on a public hostname, so the App
    Service marker has to win over the setting. Failing closed makes the API
    refuse everyone rather than serve everyone.
    """

    # Built first: the client factory resets the identity environment.
    c = make_default_client()
    os.environ["API_AUTH_MODE"] = "disabled"
    os.environ.pop(APP_SERVICE_MARKER, None)
    assert api_auth_mode() == "disabled"

    os.environ[APP_SERVICE_MARKER] = "app-asg-api-example"
    try:
        assert api_auth_mode() == "entra"
        assert c.get("/api/me", headers={"x-ms-client-principal": ""}).status_code == 401
    finally:
        os.environ.pop(APP_SERVICE_MARKER, None)
        os.environ["API_AUTH_MODE"] = "entra"
        c.close()


def test_local_dev_mode_yields_a_usable_set_of_districts() -> None:
    """The local loop must work without hand-editing DISTRICT_ASSIGNMENTS.

    populate-env.ps1 writes `API_AUTH_MODE=disabled` and nothing else, so the
    development principal has no explicit assignments. It is a facilitator, so
    `available_districts` still resolves to the roster - which is what the UI
    renders a picker from. If that ever stops being true, `npm run dev` lands
    on "No districts assigned" with no way forward.
    """

    c = make_default_client()
    os.environ["API_AUTH_MODE"] = "disabled"
    os.environ["DISTRICT_ASSIGNMENTS"] = ""
    os.environ["FACILITATOR_OBJECT_IDS"] = ""
    os.environ.pop(APP_SERVICE_MARKER, None)
    try:
        body = c.get("/api/me").json()
        assert body["is_facilitator"] is True
        assert body["available_districts"] == sorted(KNOWN_DISTRICTS)
    finally:
        os.environ["API_AUTH_MODE"] = "entra"
        c.close()


def test_a_forged_principal_header_is_honoured_documenting_the_trust_model() -> None:
    """Pins the boundary this design depends on.

    The app does not verify the principal header, because Easy Auth strips any
    client-supplied copy and injects its own. This test exists so that the
    trust is a recorded decision rather than an assumption: if the header ever
    stops being platform-guaranteed, this is the behaviour that becomes a
    vulnerability.
    """

    c = make_default_client()
    os.environ["API_AUTH_MODE"] = "entra"
    os.environ["DISTRICT_ASSIGNMENTS"] = f"{OTHER_OID}=DIST-A"
    os.environ["FACILITATOR_OBJECT_IDS"] = ""

    response = c.get("/api/me", headers=principal_header(object_id=OTHER_OID))
    assert response.status_code == 200
    assert response.json()["districts"] == ["DIST-A"]
    c.close()


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
    # The UI offers exactly this list, so a stray entry here is a data leak.
    assert body["available_districts"] == []


def test_available_districts_is_the_assignment_not_the_roster(client: TestClient) -> None:
    _restrict_to("DIST-A")
    body = client.get("/api/me").json()
    assert body["available_districts"] == ["DIST-A"]


def test_facilitator_available_districts_covers_the_roster(client: TestClient) -> None:
    """A facilitator has no explicit assignment, so the UI needs the roster."""

    os.environ["DISTRICT_ASSIGNMENTS"] = ""
    os.environ["FACILITATOR_OBJECT_IDS"] = TEST_PRINCIPAL_OID
    body = client.get("/api/me").json()
    assert body["districts"] == []
    assert body["available_districts"] == sorted(KNOWN_DISTRICTS)


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
