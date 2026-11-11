"""Static configuration for the local prototype.

Foundry Agent Service settings are read from environment.
No secrets are baked in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

SEED: int = 20260101
BASE_TIMESTAMP: str = "2026-01-05T09:00:00Z"
SERVICE_NAME: str = "agentic-support-guide-api"
SERVICE_VERSION: str = "0.3.0"

PROTOTYPE_BANNER: str = (
    "Prototype - synthetic data, three collaborating agents hosted in "
    "Foundry Agent Service, not a production system."
)

# What `RecommendationEnvelope.provider_model` reports. The per-step models
# are in the trace; this names the provider the workflow ran against.
# apps/web/src/pages/SupportsPage.tsx matches the configured string.
PROVIDER_DISPLAY_CONFIGURED: str = "Microsoft Foundry (Agent Framework, prompt agents)"
PROVIDER_DISPLAY_UNCONFIGURED: str = "unconfigured (Microsoft Foundry not set up)"

# Per-run remote agent budget (single Foundry run).
FOUNDRY_RUN_TIMEOUT_SECONDS: float = 30.0
# Whole-workflow budget across all remote agent invocations.
ORCHESTRATION_TOTAL_BUDGET_SECONDS: float = 120.0
CONCERN_TEXT_MAX_LEN: int = 1000

CONTRACT_VERSION: str = "1.0.0"


@dataclass(frozen=True)
class MockDataCounts:
    dealerships: int = 120
    # Area scores and operations are complete grids, so their record counts are
    # derived from periods rather than chosen independently.
    score_periods: int = 6
    resources: int = 40
    audit_events: int = 60
    seeded_plans: int = 10


COUNTS = MockDataCounts()


@dataclass(frozen=True)
class AzureFoundrySettings:
    """Runtime settings for Foundry Agent Service.

    - `project_endpoint`: the Foundry project endpoint. Required.
    - `application_insights_connection_string`: optional telemetry sink.
    - `auth_mode`: only "entra" (Microsoft Entra ID) is supported.
    - `demo_reset_enabled`: dev/demo toggle for /api/demo/reset.
    """

    project_endpoint: str | None
    auth_mode: str
    application_insights_connection_string: str | None
    demo_reset_enabled: bool

    @property
    def configured(self) -> bool:
        return bool(self.project_endpoint)


def load_foundry_settings() -> AzureFoundrySettings:
    endpoint = (
        os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
        or None
    )
    return AzureFoundrySettings(
        project_endpoint=endpoint,
        auth_mode=os.environ.get("AZURE_AI_FOUNDRY_AUTH_MODE", "entra"),
        application_insights_connection_string=(
            os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING") or None
        ),
        demo_reset_enabled=(
            os.environ.get("DEMO_RESET_ENABLED", "false").strip().lower() == "true"
        ),
    )
