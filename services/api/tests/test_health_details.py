from __future__ import annotations

from app.config import AzureFoundrySettings

from .conftest import make_default_client


def test_health_details_reports_test_double_and_not_ready() -> None:
    client = make_default_client()
    body = client.get("/api/health/details").json()

    assert body["status"] == "ok"
    assert body["service"] == "agentic-support-guide-api"
    assert body["active_provider"] == "test_double"
    assert body["customer_demo_ready"] is False
    assert body["foundry_configured"] is False
    assert body["foundry_project_config_present"] is False
    assert body["deployment_config_present"] is False
    assert body["application_insights_configured"] is False
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


CANARY_ENDPOINT = "https://sensitive-endpoint-value.example.invalid/"
CANARY_PROJECT = "SENSITIVE_PROJECT_NAME_CANARY"
CANARY_DEPLOYMENT = "SENSITIVE_DEPLOYMENT_NAME_CANARY"
CANARY_API_VERSION = "SENSITIVE_API_VERSION_CANARY"
CANARY_CONN_STR = "InstrumentationKey=SENSITIVE_CANARY_KEY;IngestionEndpoint=hidden"


def test_health_details_does_not_leak_any_configured_env_values() -> None:
    """Configured environment values must not appear anywhere in the payload."""

    client = make_default_client()
    client.app.state.settings = AzureFoundrySettings(  # type: ignore[attr-defined]
        endpoint=CANARY_ENDPOINT,
        project_name=CANARY_PROJECT,
        deployment=CANARY_DEPLOYMENT,
        api_version=CANARY_API_VERSION,
        auth_mode="entra",
        application_insights_connection_string=CANARY_CONN_STR,
        demo_reset_enabled=False,
    )

    body = client.get("/api/health/details").json()
    payload = str(body)
    for canary in (
        CANARY_ENDPOINT,
        CANARY_PROJECT,
        CANARY_DEPLOYMENT,
        CANARY_API_VERSION,
        CANARY_CONN_STR,
    ):
        assert canary not in payload, f"leaked configured value: {canary!r}"


def test_health_details_reports_customer_demo_ready_true_with_azure_provider() -> None:
    from unittest.mock import patch

    from app.llm import AzureFoundryLlmProvider

    client = make_default_client()
    # Swap in a bare Azure provider (no live network - the health endpoint
    # never calls the model). Also mark settings as fully configured.
    with patch.object(AzureFoundryLlmProvider, "__init__", return_value=None):
        provider = AzureFoundryLlmProvider.__new__(AzureFoundryLlmProvider)
    provider.model = "chat-deployment"
    client.app.state.provider = provider  # type: ignore[attr-defined]
    client.app.state.settings = AzureFoundrySettings(  # type: ignore[attr-defined]
        endpoint="https://foo.example.invalid/",
        project_name="p",
        deployment="d",
        api_version="v",
        auth_mode="entra",
        application_insights_connection_string="conn",
        demo_reset_enabled=False,
    )

    body = client.get("/api/health/details").json()
    assert body["active_provider"] == "azure_foundry"
    assert body["customer_demo_ready"] is True
    assert body["foundry_configured"] is True
