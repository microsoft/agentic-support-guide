"""Setup diagnostics for the demo-friendly /api/health/details endpoint.

Returns human-readable configuration status only. Never includes secrets,
endpoint URLs, tokens, connection strings, or raw environment values.

`SetupState.inspect` decides what is true; `_checks`, `_warnings` and
`_guidance` decide how to say it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agents.data_analyst.agent import AGENT_NAME as DATA_ANALYST_NAME
from .agents.support_recommender.agent import AGENT_NAME as RECOMMENDER_NAME
from .agents.validator.agent import AGENT_NAME as VALIDATOR_NAME
from .auth import api_auth_mode
from .config import AzureFoundrySettings
from .dealer_groups import KNOWN_DEALER_GROUPS
from .evidence import EvidenceRetriever
from .foundry_agents import PROVIDER_ID, MafAgentRuntime, missing_model_deployments
from .models import HealthCheckItem, HealthDetailsResponse

SERVICE_STATUS = "ok"
REQUIRED_ROLES: tuple[str, ...] = (
    DATA_ANALYST_NAME,
    RECOMMENDER_NAME,
    VALIDATOR_NAME,
)

# dealer_group_id is required by the contracts themselves, so this is a
# property of the build rather than of the environment.
DEALER_GROUP_ISOLATION_ENABLED = True


@dataclass(frozen=True)
class SetupState:
    """What is actually configured, decided without any network calls.

    The frontend polls /api/health/details on every page load, so every field
    here has to be answerable locally.
    """

    project_configured: bool
    deployments_configured: bool
    missing_deployments: tuple[str, ...]
    definitions_valid: bool
    evidence_available: bool
    evidence_verified: bool
    evidence_source: str
    evidence_knowledge_base: str
    auth_mode: str
    application_insights_configured: bool

    @classmethod
    def inspect(
        cls,
        settings: AzureFoundrySettings,
        runtime: MafAgentRuntime | None,
        evidence_retriever: EvidenceRetriever | None,
    ) -> SetupState:
        missing = tuple(missing_model_deployments())
        available = evidence_retriever is not None and any(
            evidence_retriever.has_dealer_group(g) for g in KNOWN_DEALER_GROUPS
        )
        return cls(
            project_configured=settings.configured,
            deployments_configured=not missing,
            missing_deployments=missing,
            # There are no persisted agents to bind to: a role is ready when
            # its definition loads and its model deployment env var is set.
            definitions_valid=runtime is not None and runtime.all_roles_available(REQUIRED_ROLES),
            evidence_available=available,
            # A remote retriever cannot confirm evidence exists without a
            # network call, so configuration and verification are reported as
            # two different things instead of being conflated.
            evidence_verified=available
            and getattr(evidence_retriever, "evidence_verifiable", True),
            evidence_source=getattr(evidence_retriever, "provider_name", "none"),
            evidence_knowledge_base=getattr(evidence_retriever, "provider_model", ""),
            auth_mode=settings.auth_mode,
            application_insights_configured=bool(settings.application_insights_connection_string),
        )

    @property
    def active_provider(self) -> str:
        ready = (
            self.project_configured
            and self.definitions_valid
            and self.deployments_configured
            and self.evidence_available
        )
        return PROVIDER_ID if ready else "unconfigured"


def _evidence_check(state: SetupState) -> HealthCheckItem:
    if state.evidence_verified:
        label = "Synthetic evidence fixture available"
        detail = "At least one group-scoped fixture is present."
    elif state.evidence_available:
        label = "Evidence source configured (not verified)"
        detail = (
            f"Configured against {state.evidence_source!r}. Presence of evidence "
            "is not checked here; run a real request to confirm."
        )
    else:
        label = "Evidence source configured (not verified)"
        detail = "No group-scoped fixtures loaded."
    return HealthCheckItem(
        name="evidence_fixture",
        label=label,
        ok=state.evidence_available,
        detail=detail,
    )


def _checks(state: SetupState) -> list[HealthCheckItem]:
    entra = state.auth_mode == "entra"
    return [
        HealthCheckItem(
            name="backend",
            label="Backend service running",
            ok=True,
            detail="FastAPI is responding to requests.",
        ),
        HealthCheckItem(
            name="foundry_project_endpoint",
            label="Microsoft Foundry project endpoint configured",
            ok=state.project_configured,
            detail=(
                "Set. Endpoint value hidden."
                if state.project_configured
                else "Not set. Populate AZURE_AI_FOUNDRY_PROJECT_ENDPOINT."
            ),
        ),
        HealthCheckItem(
            name="model_deployments_configured",
            label="Per-role model deployments configured",
            ok=state.deployments_configured,
            detail=(
                "All three role deployments are set."
                if state.deployments_configured
                else (
                    f"Missing: {', '.join(state.missing_deployments)}. "
                    "Run .\\scripts\\populate-env.ps1."
                )
            ),
        ),
        HealthCheckItem(
            name="agent_definitions_valid",
            label="Agent definitions loaded",
            ok=state.definitions_valid,
            detail=(
                "All three role definitions loaded from /agents."
                if state.definitions_valid
                else "One or more agent definitions could not be loaded."
            ),
        ),
        _evidence_check(state),
        HealthCheckItem(
            name="dealer_group_isolation",
            label="Dealer group isolation enforced by contracts",
            ok=DEALER_GROUP_ISOLATION_ENABLED,
            detail=(
                "dealer_group_id is required on every request, envelope, "
                "citation, audit row, and trace."
            ),
        ),
        HealthCheckItem(
            name="auth_mode",
            label="Foundry authentication mode",
            ok=entra,
            detail=(
                "This API authenticates to Microsoft Foundry with Microsoft Entra ID "
                "(no keys). Separate from api_auth_mode, which is how callers "
                "authenticate to this API."
                if entra
                else "Non-default Foundry auth mode. Only 'entra' is supported by this build."
            ),
        ),
        HealthCheckItem(
            name="application_insights",
            label="Application Insights configured",
            ok=state.application_insights_configured,
            detail=(
                "Set. Telemetry emits metadata only."
                if state.application_insights_configured
                else "Not set (optional). Telemetry no-ops."
            ),
        ),
    ]


def _warnings(state: SetupState) -> list[str]:
    """Only the first unmet prerequisite in the chain is reported.

    Reporting unloadable agent definitions is noise when the real problem is
    that no project endpoint has been configured yet.
    """

    warnings: list[str] = []
    if not state.project_configured:
        warnings.append(
            "Microsoft Foundry project endpoint is not configured. Recommendation "
            "requests will fail with a typed provider_missing error until "
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is set."
        )
    elif not state.deployments_configured:
        warnings.append(
            "Foundry project is configured but per-role model deployments are "
            "missing. Run .\\scripts\\populate-env.ps1 to regenerate "
            "services/api/.env, then restart the backend with --env-file .env."
        )
    elif not state.definitions_valid:
        warnings.append(
            "Agent definitions in /agents could not be loaded. Run "
            "'python scripts/validate_agent_definitions.py' to see why."
        )
    if not state.evidence_available:
        warnings.append(
            "No group-scoped evidence fixture is loaded. Recommendation requests "
            "will return evidence_missing until a fixture is registered."
        )
    return warnings


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


def build_health_details(
    *,
    settings: AzureFoundrySettings,
    runtime: MafAgentRuntime | None,
    evidence_retriever: EvidenceRetriever | None,
    service: str,
    version: str,
) -> HealthDetailsResponse:
    state = SetupState.inspect(settings, runtime, evidence_retriever)
    active_provider = state.active_provider
    remote_workflow_active = active_provider == PROVIDER_ID

    return HealthDetailsResponse(
        status=SERVICE_STATUS,
        service=service,
        version=version,
        active_provider=active_provider,
        foundry_project_configured=state.project_configured,
        agent_definitions_valid=state.definitions_valid,
        model_deployments_configured=state.deployments_configured,
        service_side_remote_workflow_active=remote_workflow_active,
        evidence_fixture_available=state.evidence_available,
        evidence_source=state.evidence_source,
        evidence_verified=state.evidence_verified,
        api_auth_mode=api_auth_mode(),
        evidence_knowledge_base=state.evidence_knowledge_base,
        dealer_group_isolation_enabled=DEALER_GROUP_ISOLATION_ENABLED,
        customer_demo_ready=remote_workflow_active,
        checks=_checks(state),
        warnings=_warnings(state),
        guidance=_guidance(active_provider),
    )
