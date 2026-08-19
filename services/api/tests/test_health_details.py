from __future__ import annotations

from app.config import AzureFoundrySettings

from .conftest import make_default_client


def test_health_details_reports_ready_with_fake_bindings_and_fixture() -> None:
    client = make_default_client()
    body = client.get("/api/health/details").json()
    assert body["status"] == "ok"
    assert body["service"] == "agentic-support-guide-api"
    assert body["active_provider"] == "azure_foundry_agents"
    assert body["foundry_project_configured"] is True
    assert body["foundry_agents_bound"] is True
    assert body["service_side_remote_workflow_active"] is True
    assert body["evidence_fixture_available"] is True
    assert body["district_isolation_enabled"] is True
    assert body["customer_demo_ready"] is True
    assert any(check["name"] == "backend" and check["ok"] for check in body["checks"])
    assert any(check["name"] == "foundry_project_endpoint" for check in body["checks"])
    assert any(check["name"] == "agent_bindings" for check in body["checks"])
    assert any(check["name"] == "evidence_fixture" for check in body["checks"])
    assert any(check["name"] == "district_isolation" for check in body["checks"])


def test_health_details_unconfigured_when_project_endpoint_missing() -> None:
    client = make_default_client()
    client.app.state.settings = AzureFoundrySettings(  # type: ignore[attr-defined]
        project_endpoint=None,
        auth_mode="entra",
        application_insights_connection_string=None,
        demo_reset_enabled=False,
    )
    body = client.get("/api/health/details").json()

    assert body["active_provider"] == "unconfigured"
    assert body["foundry_project_configured"] is False
    assert body["service_side_remote_workflow_active"] is False
    assert body["customer_demo_ready"] is False
    assert body["warnings"]


def test_health_details_unconfigured_when_bindings_missing() -> None:
    client = make_default_client()
    client.app.state.adapter = None  # type: ignore[attr-defined]
    body = client.get("/api/health/details").json()

    assert body["active_provider"] == "unconfigured"
    assert body["foundry_agents_bound"] is False
    assert body["service_side_remote_workflow_active"] is False
    assert body["customer_demo_ready"] is False


def test_health_details_does_not_expose_secrets() -> None:
    client = make_default_client()
    body = client.get("/api/health/details").json()
    payload = str(body).lower()
    for forbidden in ("connection_string=", "endpoint=", "secret", "key=", "token"):
        assert forbidden not in payload


CANARY_ENDPOINT = "https://sensitive-endpoint-value.example.invalid/api/projects/asg"
CANARY_CONN_STR = "InstrumentationKey=SENSITIVE_CANARY_KEY;IngestionEndpoint=hidden"


def test_health_details_does_not_leak_any_configured_env_values() -> None:
    client = make_default_client()
    client.app.state.settings = AzureFoundrySettings(  # type: ignore[attr-defined]
        project_endpoint=CANARY_ENDPOINT,
        auth_mode="entra",
        application_insights_connection_string=CANARY_CONN_STR,
        demo_reset_enabled=False,
    )

    body = client.get("/api/health/details").json()
    payload = str(body)
    for canary in (CANARY_ENDPOINT, CANARY_CONN_STR):
        assert canary not in payload
