from __future__ import annotations

from .conftest import make_default_client


def test_health_details_reports_test_double_and_not_ready() -> None:
    client = make_default_client()
    body = client.get("/api/health/details").json()

    assert body["status"] == "ok"
    assert body["service"] == "agentic-support-guide-api"
    assert body["active_provider"] == "test_double"
    assert body["customer_demo_ready"] is False
    assert any(check["name"] == "backend" and check["ok"] for check in body["checks"])
    assert any(check["name"] == "foundry_endpoint" for check in body["checks"])
    assert any(check["name"] == "foundry_deployment" for check in body["checks"])
    assert body["warnings"], "warnings must call out that test double is not for demo"
    assert "test-double" in " ".join(body["warnings"]).lower()


def test_health_details_does_not_expose_secrets() -> None:
    client = make_default_client()
    body = client.get("/api/health/details").json()
    payload = str(body).lower()
    for forbidden in ("connection_string=", "endpoint=", "secret", "key=", "token"):
        assert forbidden not in payload
