from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import AzureFoundrySettings
from app.llm import LlmProvider, MockLlmProvider
from app.main import create_app

ENV_KEYS = (
    "AZURE_AI_FOUNDRY_ENDPOINT",
    "AZURE_AI_FOUNDRY_PROJECT_NAME",
    "AZURE_AI_FOUNDRY_DEPLOYMENT",
    "AZURE_AI_FOUNDRY_API_VERSION",
    "AZURE_AI_FOUNDRY_AUTH_MODE",
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "DEMO_RESET_ENABLED",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def canned_data_analyst_output() -> dict[str, Any]:
    return {
        "contract_version": "1.0.0",
        "analysis": {
            "detected_need": "Early literacy skill gap",
            "evidence_bullets": [
                "Proficiency index below target across two windows.",
                "Attendance within expected range.",
            ],
            "missing_data_flags": [],
            "analysis_confidence": 0.8,
        },
    }


def canned_recommendation_draft(
    *,
    resource_ids: list[str] | None = None,
    smart_goal_ids: list[str] | None = None,
    strategy_ids: list[str] | None = None,
    tier: str = "Targeted support (Tier 2)",
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": "1.0.0",
        "detected_need": "Early literacy skill gap",
        "support_tier": tier,
        "recommended_frequency": "3x weekly, 20-25 min",
        "grouping_guidance": "small group of 3-5",
        "resource_ids": resource_ids if resource_ids is not None else [],
        "rationale": "Synthetic learner indicators support targeted early-literacy work.",
        "smart_goal_suggestions": smart_goal_ids if smart_goal_ids is not None else [],
        "strategy_suggestions": strategy_ids if strategy_ids is not None else [],
        "educator_next_steps": ["Confirm baseline with a short synthetic probe."],
        "progress_monitoring": ["Weekly 3-minute probe."],
        "review_window_days": 28,
        "decision_rule": "IF proficiency_index < 60 THEN targeted.",
        "caveats": caveats
        if caveats is not None
        else [
            "Illustrative synthetic output only; not a real benchmark.",
            "Human review is required before any decision or communication.",
        ],
    }


def canned_validator_critique() -> dict[str, Any]:
    return {"warning_codes": [], "repair_guidance": ""}


def _canned_mock_provider() -> MockLlmProvider:
    provider = MockLlmProvider()
    provider.register("data_analyst_output", canned_data_analyst_output())
    provider.register(
        "support_recommendation_draft",
        canned_recommendation_draft(
            smart_goal_ids=["SG-early-literacy-1"],
            strategy_ids=["ST-early-literacy-1"],
        ),
    )
    provider.register("validator_llm_critique", canned_validator_critique())
    return provider


@pytest.fixture()
def mock_provider() -> MockLlmProvider:
    return _canned_mock_provider()


@pytest.fixture()
def make_client() -> Callable[[LlmProvider, bool], TestClient]:
    def _factory(provider: LlmProvider, demo_reset_enabled: bool = False) -> TestClient:
        def factory(_settings: AzureFoundrySettings) -> LlmProvider:
            return provider

        app = create_app(provider_factory=factory)
        app.state.settings = AzureFoundrySettings(
            endpoint=None,
            project_name=None,
            deployment=None,
            api_version=None,
            auth_mode="entra",
            application_insights_connection_string=None,
            demo_reset_enabled=demo_reset_enabled,
        )
        return TestClient(app)

    return _factory


def make_default_client(*, demo_reset_enabled: bool = False) -> TestClient:
    provider = _canned_mock_provider()

    def factory(_settings: AzureFoundrySettings) -> LlmProvider:
        return provider

    app = create_app(provider_factory=factory)
    app.state.settings = AzureFoundrySettings(
        endpoint=None,
        project_name=None,
        deployment=None,
        api_version=None,
        auth_mode="entra",
        application_insights_connection_string=None,
        demo_reset_enabled=demo_reset_enabled,
    )
    return TestClient(app)
