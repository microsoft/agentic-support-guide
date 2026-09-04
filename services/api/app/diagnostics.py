"""Setup diagnostics for the demo-friendly /api/health/details endpoint.

Returns human-readable configuration status only. Never includes secrets,
endpoint URLs, tokens, connection strings, or raw environment values.
"""

from __future__ import annotations

from .agents.data_analyst.agent import AGENT_NAME as DATA_ANALYST_NAME
from .agents.support_recommender.agent import AGENT_NAME as RECOMMENDER_NAME
from .agents.validator.agent import AGENT_NAME as VALIDATOR_NAME
from .config import AzureFoundrySettings
from .evidence import EvidenceRetriever
from .foundry_agents import PROVIDER_ID, MafAgentRuntime, missing_model_deployments
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
    runtime: MafAgentRuntime | None,
    evidence_retriever: EvidenceRetriever | None,
    service: str,
    version: str,
) -> HealthDetailsResponse:
    project_configured = settings.configured
    # There are no persisted agents to bind to. A role is ready when its
    # definition loads and its model deployment env var is set - both are
    # local checks, so this endpoint stays free of network calls even though
    # the frontend polls it on every page load.
    missing_deployments = missing_model_deployments()
    deployments_configured = not missing_deployments
    definitions_valid = runtime is not None and runtime.all_roles_available(REQUIRED_ROLES)
    evidence_available = evidence_retriever is not None and any(
        evidence_retriever.has_district(d) for d in ("DIST-A", "DIST-B", "DIST-DEMO")
    )
    district_isolation_enabled = True

    if project_configured and definitions_valid and deployments_configured and evidence_available:
        active_provider = PROVIDER_ID
    else:
        active_provider = "unconfigured"

    service_side_remote_workflow_active = active_provider == PROVIDER_ID
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
            name="model_deployments_configured",
            label="Per-role model deployments configured",
            ok=deployments_configured,
            detail=(
                "All three role deployments are set."
                if deployments_configured
                else f"Missing: {', '.join(missing_deployments)}. Run .\\scripts\\populate-env.ps1."
            ),
        ),
        HealthCheckItem(
            name="agent_definitions_valid",
            label="Agent definitions loaded",
            ok=definitions_valid,
            detail=(
                "All three role definitions loaded from /agents."
                if definitions_valid
                else "One or more agent definitions could not be loaded."
            ),
        ),
        HealthCheckItem(
            name="evidence_fixture",
            label="Synthetic evidence fixture available",
            ok=evidence_available,
            detail=(
                "At least one district-scoped fixture is present."
                if evidence_available
                else "No district-scoped fixtures loaded."
            ),
        ),
        HealthCheckItem(
            name="district_isolation",
            label="District isolation enforced by contracts",
            ok=district_isolation_enabled,
            detail=(
                "district_id is required on every request, envelope, "
                "citation, audit row, and trace."
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
    elif not deployments_configured:
        warnings.append(
            "Foundry project is configured but per-role model deployments are "
            "missing. Run .\\scripts\\populate-env.ps1 to regenerate "
            "services/api/.env, then restart the backend with --env-file .env."
        )
    elif not definitions_valid:
        warnings.append(
            "Agent definitions in /agents could not be loaded. Run "
            "'python scripts/validate_agent_definitions.py' to see why."
        )
    if not evidence_available:
        warnings.append(
            "No district-scoped evidence fixture is loaded. Recommendation requests "
            "will return evidence_missing until a fixture is registered."
        )

    guidance = _guidance(active_provider)

    return HealthDetailsResponse(
        status=SERVICE_STATUS,
        service=service,
        version=version,
        active_provider=active_provider,
        foundry_project_configured=project_configured,
        agent_definitions_valid=definitions_valid,
        model_deployments_configured=deployments_configured,
        service_side_remote_workflow_active=service_side_remote_workflow_active,
        evidence_fixture_available=evidence_available,
        district_isolation_enabled=district_isolation_enabled,
        customer_demo_ready=customer_demo_ready,
        checks=checks,
        warnings=warnings,
        guidance=guidance,
    )


def _guidance(active_provider: str) -> str:
    if active_provider == PROVIDER_ID:
        return (
            "Ready for a live demo. Sign in with 'az login' if you have not already. "
            "First-request RBAC propagation may take a few minutes; retry if you see 401/403."
        )
    return (
        "Not demo-ready. To finish setup: run Terraform in /infra, run "
        ".\\scripts\\populate-env.ps1 to write services/api/.env, then start the "
        "backend with --env-file .env. No agent deployment step is needed - "
        "agent definitions live in /agents and load at runtime."
    )
