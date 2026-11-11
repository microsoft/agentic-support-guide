"""Caller authentication.

The API is reachable on a public hostname, so the shared key is what stops it
being called directly. These tests send real headers rather than disabling the
check, so the comparison path actually runs.

There is deliberately no per-user authorization to test: the web tier attaches
the key for whoever asks, so anyone who can reach the UI can reach the API
through it. That is a property of the design, recorded here so it stays a
decision rather than an assumption.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import API_KEY_HEADER, APP_SERVICE_MARKER, api_auth_mode

from .conftest import TEST_API_KEY, make_default_client

RECOMMENDATION_BODY = {
    "dealer_group_id": "GROUP-A",
    "dealership_id": "DLR-0001",
    "category": "lead-response",
    "concern_text": "Median first response to online enquiries slipped past one hour.",
}

# Reachable without a key by design: deploy-app.ps1 and CI poll this to find
# out which build is serving, before the web tier is up. Adding a route here
# is a deliberate act.
ANONYMOUS_PATHS = {"/api/health"}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    c = make_default_client()
    yield c
    c.close()


def _requires_key(dependant: object) -> bool:
    stack = [dependant]
    while stack:
        current = stack.pop()
        call = getattr(current, "call", None)
        if getattr(call, "__name__", "") == "require_api_key":
            return True
        stack.extend(getattr(current, "dependencies", []))
    return False


def test_every_route_requires_the_key_or_is_explicitly_anonymous() -> None:
    """Catches a new route added without the key check.

    Asserted against the dependency tree rather than by calling each endpoint:
    a request with no body returns 422 before authentication, which would make
    an unprotected route look protected.
    """

    from fastapi.routing import APIRoute

    from app.main import create_app

    # FastAPI stores included routers as `_IncludedRouter` wrappers, so the
    # endpoints are not in `app.routes` and have to be reached through
    # `original_router`.
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
        if route.path not in ANONYMOUS_PATHS and not _requires_key(route.dependant)
    )
    assert unprotected == [], f"routes missing the API key check: {unprotected}"


def test_no_unguarded_non_api_routes_are_served_on_app_service() -> None:
    """The docs routes are not APIRoutes, so the check above cannot see them.

    FastAPI mounts /api/openapi.json and /api/docs as plain Starlette routes,
    outside the router that carries the key dependency. On App Service they
    served the entire schema to anyone; this pins them shut.
    """

    from app.main import create_app

    os.environ[APP_SERVICE_MARKER] = "app-asg-api-example"
    try:
        paths = {getattr(r, "path", "") for r in create_app().routes}
    finally:
        os.environ.pop(APP_SERVICE_MARKER, None)

    assert "/api/openapi.json" not in paths, "OpenAPI schema is exposed on App Service"
    assert "/api/docs" not in paths, "Swagger UI is exposed on App Service"

    # Still available on a laptop, which is where learners read them.
    local_paths = {getattr(r, "path", "") for r in create_app().routes}
    assert "/api/docs" in local_paths


def test_request_without_a_key_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations/support-plan",
        json=RECOMMENDATION_BODY,
        headers={API_KEY_HEADER: ""},
    )
    assert response.status_code == 401


def test_wrong_key_is_rejected(client: TestClient) -> None:
    response = client.get("/api/supports/plans", headers={API_KEY_HEADER: "not-the-key"})
    assert response.status_code == 401


def test_correct_key_is_accepted(client: TestClient) -> None:
    response = client.get("/api/supports/plans", headers={API_KEY_HEADER: TEST_API_KEY})
    assert response.status_code == 200


def test_health_stays_anonymous(client: TestClient) -> None:
    """deploy-app.ps1 polls health to detect stale builds before the UI is up."""

    response = client.get("/api/health", headers={API_KEY_HEADER: ""})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_details_needs_the_key(client: TestClient) -> None:
    """It reports evidence source, knowledge base and readiness flags.

    That is reconnaissance for anyone choosing what to attack, and unlike
    `/api/health` nothing in the deploy path needs it anonymously.
    """

    assert client.get("/api/health/details", headers={API_KEY_HEADER: ""}).status_code == 401


def test_api_refuses_to_serve_unauthenticated_on_app_service() -> None:
    """Forgetting the setting must not be the same as turning auth off.

    Locally a missing key means "uvicorn behind the Vite dev proxy". On App
    Service it means the API is open on a public hostname, so it fails closed.
    """

    c = make_default_client()
    os.environ.pop("API_SHARED_KEY", None)
    os.environ.pop(APP_SERVICE_MARKER, None)
    try:
        assert api_auth_mode() == "unprotected"
        assert c.get("/api/supports/plans").status_code == 200

        os.environ[APP_SERVICE_MARKER] = "app-asg-api-example"
        assert api_auth_mode() == "misconfigured"
        assert c.get("/api/supports/plans").status_code == 503
    finally:
        os.environ.pop(APP_SERVICE_MARKER, None)
        os.environ["API_SHARED_KEY"] = TEST_API_KEY
        c.close()


def test_dealer_groups_come_from_the_api_not_the_bundle(client: TestClient) -> None:
    """The UI has no identity, so the roster has to be served to it."""

    body = client.get("/api/supports/options", headers={API_KEY_HEADER: TEST_API_KEY}).json()
    assert body["dealer_groups"] == ["GROUP-A", "GROUP-B", "GROUP-DEMO"]
