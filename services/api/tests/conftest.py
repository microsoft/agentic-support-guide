from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import AzureFoundrySettings
from app.evidence import FixtureEvidenceRetriever
from app.foundry_agents import MafAgentRuntime
from app.main import create_app

from .fakes import (
    DEFAULT_DEPLOYMENT,
    DEFAULT_ENDPOINT,
    FakeChatClientFactory,
    make_fake_runtime,
)

ENV_KEYS = (
    "AZURE_AI_FOUNDRY_ENDPOINT",
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "AZURE_AI_FOUNDRY_AUTH_MODE",
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "DEMO_RESET_ENABLED",
    "FOUNDRY_MODEL_DEPLOYMENT_ANALYST",
    "FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER",
    "FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR",
)

DEFAULT_DISTRICT = "DIST-DEMO"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Role readiness now derives from these instead of a bindings file.
    for key in (
        "FOUNDRY_MODEL_DEPLOYMENT_ANALYST",
        "FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER",
        "FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR",
    ):
        monkeypatch.setenv(key, DEFAULT_DEPLOYMENT)
    yield


# ---------------------------------------------------------------------
# Canonical canned agent outputs used across tests
# ---------------------------------------------------------------------


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
    cited_ids: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
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
    if cited_ids is not None:
        body["cited_ids"] = cited_ids
    else:
        # Citations are no longer auto-attached when the model cites nothing,
        # so the canned draft must cite explicitly like a real one would.
        body["cited_ids"] = ["DIST-DEMO-el-01", "DIST-DEMO-el-02"]
    return body


def canned_validator_critique() -> dict[str, Any]:
    return {"warning_codes": [], "repair_guidance": ""}


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _canned_factory(
    *,
    resource_ids: list[str] | None = None,
    smart_goal_ids: list[str] | None = None,
    strategy_ids: list[str] | None = None,
) -> FakeChatClientFactory:
    factory = FakeChatClientFactory()
    factory.register_response("data-analyst-agent", canned_data_analyst_output())
    factory.register_response(
        "support-recommendation-agent",
        canned_recommendation_draft(
            resource_ids=resource_ids,
            smart_goal_ids=smart_goal_ids or ["SG-early-literacy-1"],
            strategy_ids=strategy_ids or ["ST-early-literacy-1"],
        ),
    )
    factory.register_response("validator-agent", canned_validator_critique())
    return factory


@pytest.fixture()
def fake_factory() -> FakeChatClientFactory:
    return _canned_factory()


@pytest.fixture()
def fake_runtime(fake_factory: FakeChatClientFactory) -> MafAgentRuntime:
    runtime, _ = make_fake_runtime(fake_factory)
    return runtime


@pytest.fixture()
def evidence_retriever() -> FixtureEvidenceRetriever:
    return FixtureEvidenceRetriever()


TEST_API_KEY = "test-shared-key-not-a-real-secret"


def api_key_header() -> dict[str, str]:
    """The header the web tier attaches on every forwarded request.

    Tests send a real key rather than leaving it unset, so the comparison path
    runs. Clearing the key in tests would make every endpoint test blind to
    whether the check is wired up at all.
    """

    return {"x-api-key": TEST_API_KEY}


def _apply_test_identity() -> None:
    os.environ["API_SHARED_KEY"] = TEST_API_KEY


@pytest.fixture()
def make_client() -> Callable[..., TestClient]:
    def _factory(
        runtime: MafAgentRuntime | None = None,
        *,
        demo_reset_enabled: bool = False,
        project_endpoint: str | None = DEFAULT_ENDPOINT,
    ) -> TestClient:
        if runtime is None:
            runtime, _ = make_fake_runtime(_canned_factory())
        app = create_app(runtime=runtime)
        app.state.settings = AzureFoundrySettings(
            project_endpoint=project_endpoint,
            auth_mode="entra",
            application_insights_connection_string=None,
            demo_reset_enabled=demo_reset_enabled,
        )
        app.state.runtime = runtime
        _apply_test_identity()
        return TestClient(app, headers=api_key_header())

    return _factory


def make_default_client(*, demo_reset_enabled: bool = False) -> TestClient:
    runtime, _ = make_fake_runtime(_canned_factory())
    app = create_app(runtime=runtime)
    app.state.settings = AzureFoundrySettings(
        project_endpoint=DEFAULT_ENDPOINT,
        auth_mode="entra",
        application_insights_connection_string=None,
        demo_reset_enabled=demo_reset_enabled,
    )
    app.state.runtime = runtime
    _apply_test_identity()
    return TestClient(app, headers=api_key_header())
