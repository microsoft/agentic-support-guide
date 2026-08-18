"""Static configuration for the local prototype.

Azure OpenAI settings are read from environment. No secrets are baked in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

SEED: int = 20260101
BASE_TIMESTAMP: str = "2026-01-05T09:00:00Z"
SERVICE_NAME: str = "agentic-support-guide-api"
SERVICE_VERSION: str = "0.2.0"

PROTOTYPE_BANNER: str = (
    "Prototype - synthetic data, three agents backed by Azure AI Foundry, not a production system."
)

AGENT_REQUEST_TIMEOUT_SECONDS: float = 30.0
ORCHESTRATION_TOTAL_BUDGET_SECONDS: float = 90.0
AGENT_MAX_OUTPUT_TOKENS: int = 800
AGENT_MAX_RETRIES: int = 3
CONCERN_TEXT_MAX_LEN: int = 1000
PROCESS_LLM_CALL_CEILING: int = 500

CONTRACT_VERSION: str = "1.0.0"


@dataclass(frozen=True)
class MockDataCounts:
    learners: int = 120
    assessments: int = 400
    behavior_records: int = 150
    resources: int = 40
    audit_events: int = 60
    seeded_plans: int = 10


COUNTS = MockDataCounts()


@dataclass(frozen=True)
class AzureFoundrySettings:
    endpoint: str | None
    project_name: str | None
    deployment: str | None
    api_version: str | None
    auth_mode: str
    application_insights_connection_string: str | None
    demo_reset_enabled: bool

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.deployment and self.api_version)


DEFAULT_FOUNDRY_API_VERSION = "2024-10-21"


def load_foundry_settings() -> AzureFoundrySettings:
    return AzureFoundrySettings(
        endpoint=os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT") or None,
        project_name=os.environ.get("AZURE_AI_FOUNDRY_PROJECT_NAME") or None,
        deployment=os.environ.get("AZURE_AI_FOUNDRY_DEPLOYMENT") or None,
        api_version=os.environ.get("AZURE_AI_FOUNDRY_API_VERSION")
        or (DEFAULT_FOUNDRY_API_VERSION if os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT") else None),
        auth_mode=os.environ.get("AZURE_AI_FOUNDRY_AUTH_MODE", "entra"),
        application_insights_connection_string=(
            os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING") or None
        ),
        demo_reset_enabled=(
            os.environ.get("DEMO_RESET_ENABLED", "false").strip().lower() == "true"
        ),
    )
