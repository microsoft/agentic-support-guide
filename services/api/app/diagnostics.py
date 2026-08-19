"""Setup diagnostics for the demo-friendly /api/health/details endpoint.

Returns human-readable configuration status only. Never includes secrets,
endpoint URLs, tokens, connection strings, or raw environment values.
"""

from __future__ import annotations

from .agents.data_analyst.agent import AGENT_NAME as DATA_ANALYST_NAME
from .agents.support_recommender.agent import AGENT_NAME as RECOMMENDER_NAME
from .agents.validator.agent import AGENT_NAME as VALIDATOR_NAME
from .config import AzureFoundrySettings
from .foundry_agents import FoundryRemoteAgentAdapter
from .models import HealthCheckItem, HealthDetailsResponse

SERVICE_STATUS = "ok"
REQUIRED_ROLES: tuple[str, ...] = (
    DATA_ANALYST_NAME,
    RECOMMENDER_NAME,
    VALIDATOR_NAME,
)


def build_health_details(
    *,
    settings: AzureFoundrySettings,
    adapter: FoundryRemoteAgentAdapter | None,
    service: str,
    version: str,
) -> HealthDetailsResponse:
    project_configured = settings.configured
    agents_bound = adapter is not None and adapter.all_roles_bound(REQUIRED_ROLES)

    # Runtime is "azure_foundry_agents" only when both the project is
    # configured AND all three roles are bound to remote assistants.
    if project_configured and agents_bound:
        active_provider = "azure_foundry_agents"
    else:
        active_provider = "unconfigured"

    service_side_remote_workflow_active = active_provider == "azure_foundry_agents"
    customer_demo_ready = service_side_remote_workflow_active

    checks: list[HealthCheckItem] = [
        HealthCheckItem(
            name="backend",
            label="Backend service running",
            ok=True,
            detail="FastAPI is responding to requests.",
        ),
        HealthCheckItem(
            name="foundry_project_endpoint",
            label="Azure AI Foundry project endpoint configured",
            ok=project_configured,
            detail=(
                "Set. Endpoint value hidden."
                if project_configured
                else "Not set. Populate AZURE_AI_FOUNDRY_PROJECT_ENDPOINT."
            ),
        ),
        HealthCheckItem(
            name="agent_bindings",
            label="Foundry agent bindings present",
            ok=agents_bound,
            detail=(
                "All required roles are bound to remote Foundry agents."
                if agents_bound
                else "One or more roles are not bound. Run "
                "scripts/sync_foundry_agents.py --apply."
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
    if not project_configured:
        warnings.append(
            "Azure AI Foundry project endpoint is not configured. Recommendation "
            "requests will fail with a typed provider_missing error until "
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is set."
        )
    elif not agents_bound:
        warnings.append(
            "Foundry project is configured but agent bindings are missing. Run "
            "scripts/sync_foundry_agents.py --apply to create/update remote "
            "agents from the /agents definitions."
        )

    guidance = _guidance(active_provider)

    return HealthDetailsResponse(
        status=SERVICE_STATUS,
        service=service,
        version=version,
        active_provider=active_provider,
        foundry_project_configured=project_configured,
        foundry_agents_bound=agents_bound,
        service_side_remote_workflow_active=service_side_remote_workflow_active,
        customer_demo_ready=customer_demo_ready,
        checks=checks,
        warnings=warnings,
        guidance=guidance,
    )


def _guidance(active_provider: str) -> str:
    if active_provider == "azure_foundry_agents":
        return (
            "Ready for a live demo. Sign in with 'az login' if you have not already. "
            "First-request RBAC propagation may take a few minutes; retry if you see 401/403."
        )
    return (
        "Not demo-ready. To finish setup: run Terraform in /infra, populate "
        "services/api/.env with AZURE_AI_FOUNDRY_PROJECT_ENDPOINT, run "
        "scripts/sync_foundry_agents.py --apply, then restart the backend."
    )
