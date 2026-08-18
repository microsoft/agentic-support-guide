"""Setup diagnostics for the demo-friendly /api/health/details endpoint.

Returns human-readable configuration status only. Never includes secrets,
endpoint URLs, tokens, connection strings, or raw environment values.
"""

from __future__ import annotations

from .config import AzureFoundrySettings
from .llm import LlmProvider
from .models import HealthCheckItem, HealthDetailsResponse

SERVICE_STATUS = "ok"


def build_health_details(
    *,
    settings: AzureFoundrySettings,
    provider: LlmProvider,
    service: str,
    version: str,
) -> HealthDetailsResponse:
    if provider.name == "azure-openai":
        active_provider = "azure_foundry"
    elif provider.name == "mock":
        active_provider = "test_double"
    else:
        active_provider = "unconfigured"

    customer_demo_ready = active_provider == "azure_foundry" and settings.configured

    checks: list[HealthCheckItem] = [
        HealthCheckItem(
            name="backend",
            label="Backend service running",
            ok=True,
            detail="FastAPI is responding to requests.",
        ),
        HealthCheckItem(
            name="foundry_endpoint",
            label="Azure AI Foundry endpoint configured",
            ok=bool(settings.endpoint),
            detail=(
                "Set. Endpoint value hidden."
                if settings.endpoint
                else "Not set. Populate AZURE_AI_FOUNDRY_ENDPOINT from Terraform outputs."
            ),
        ),
        HealthCheckItem(
            name="foundry_project",
            label="Azure AI Foundry project name",
            ok=bool(settings.project_name),
            detail=(
                "Set."
                if settings.project_name
                else "Not set. Populate AZURE_AI_FOUNDRY_PROJECT_NAME (observability)."
            ),
        ),
        HealthCheckItem(
            name="foundry_deployment",
            label="Model deployment name",
            ok=bool(settings.deployment),
            detail=(
                "Set."
                if settings.deployment
                else "Not set. Populate AZURE_AI_FOUNDRY_DEPLOYMENT with your model deployment."
            ),
        ),
        HealthCheckItem(
            name="foundry_api_version",
            label="Azure AI Foundry API version",
            ok=bool(settings.api_version),
            detail=(
                f"Set (using {settings.api_version})."
                if settings.api_version
                else "Not set. Use the documented default API version."
            ),
        ),
        HealthCheckItem(
            name="auth_mode",
            label="Authentication mode",
            ok=settings.auth_mode == "entra",
            detail=(
                "Keyless (Microsoft Entra ID). Requires az login and RBAC role assignments."
                if settings.auth_mode == "entra"
                else "Non-default auth mode. Only 'entra' is supported by this build."
            ),
        ),
        HealthCheckItem(
            name="application_insights",
            label="Application Insights configured",
            ok=bool(settings.application_insights_connection_string),
            detail=(
                "Set. Telemetry emits metadata only."
                if settings.application_insights_connection_string
                else "Not set (optional). Telemetry no-ops."
            ),
        ),
    ]

    warnings: list[str] = []
    if active_provider == "unconfigured":
        warnings.append(
            "Azure AI Foundry environment variables are missing. "
            "Recommendation requests will fail with a typed provider_missing error "
            "until services/api/.env is populated from the Terraform outputs."
        )
    if active_provider == "test_double":
        warnings.append(
            "A test-double LLM provider is currently registered. This build path is "
            "reserved for automated tests. Customer demos must use Azure AI Foundry."
        )

    guidance = _guidance(active_provider)

    return HealthDetailsResponse(
        status=SERVICE_STATUS,
        service=service,
        version=version,
        active_provider=active_provider,
        customer_demo_ready=customer_demo_ready,
        checks=checks,
        warnings=warnings,
        guidance=guidance,
    )


def _guidance(active_provider: str) -> str:
    if active_provider == "azure_foundry":
        return (
            "Ready for a live demo. Sign in with 'az login' if you have not already. "
            "First-request RBAC propagation may take a few minutes; retry if you see 401/403."
        )
    if active_provider == "test_double":
        return (
            "The backend is currently wired to a test-double provider. Not suitable for a "
            "customer demo. Restart the backend with Azure AI Foundry environment variables "
            "populated."
        )
    return (
        "Not demo-ready. To finish setup: run Terraform in /infra, then copy the outputs "
        "into services/api/.env and restart the backend."
    )
