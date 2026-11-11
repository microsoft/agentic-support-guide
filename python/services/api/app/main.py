"""Application wiring.

`create_app` builds the dependency graph, puts it on `app.state`, and mounts
the routers. The routes themselves live in `app/routers/`, and the agent
workflow in `app/workflows/`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import running_on_app_service
from .config import (
    FOUNDRY_RUN_TIMEOUT_SECONDS,
    SERVICE_VERSION,
    AzureFoundrySettings,
    load_foundry_settings,
)
from .contracts_registry import load_registry
from .evidence import EvidenceRetriever, FixtureEvidenceRetriever
from .foundry_agents import (
    FoundryResponsesClientFactory,
    MafAgentRuntime,
    default_credential_factory,
    load_role_definitions,
)
from .observability import configure_observability
from .plans_store import SavedPlansStore
from .repositories import build_repositories
from .routers import audit, health, insights, plans, supports
from .runtime_audit import RuntimeAuditLog
from .services import STATE_ATTR, AppServices

# Vite dev server. Override with a comma-separated ALLOWED_ORIGINS when the
# API is served anywhere other than the local dev proxy.
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


def _allowed_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    configured = [o.strip() for o in raw.split(",") if o.strip()]
    return configured or list(DEFAULT_ALLOWED_ORIGINS)


def _build_evidence_retriever() -> EvidenceRetriever:
    """Fixtures or Foundry IQ, chosen by EVIDENCE_SOURCE.

    Fixtures are the default so tests and CI stay offline and free. Setting
    EVIDENCE_SOURCE=foundry_iq is what makes the app serve real retrieved
    evidence instead of in-memory data.
    """

    source = os.environ.get("EVIDENCE_SOURCE", "fixtures").strip().lower()
    if source in ("", "fixtures"):
        return FixtureEvidenceRetriever()
    if source == "foundry_iq":
        from .evidence.foundry_iq import FoundryIQEvidenceRetriever

        return FoundryIQEvidenceRetriever(
            endpoint=os.environ.get("AZURE_SEARCH_ENDPOINT", ""),
            knowledge_base=os.environ.get("FOUNDRY_IQ_KNOWLEDGE_BASE", ""),
            knowledge_source=os.environ.get("FOUNDRY_IQ_KNOWLEDGE_SOURCE", ""),
        )
    raise ValueError(f"Unknown EVIDENCE_SOURCE {source!r}. Use 'fixtures' or 'foundry_iq'.")


def _build_runtime(
    settings: AzureFoundrySettings,
    client_factory: Callable[[str], Any] | None,
) -> MafAgentRuntime | None:
    """Assemble role definitions from agent.md + per-role model deployments.

    There are no persisted agents to look up: a role is available when its
    definition loads and its model deployment env var is set.
    """

    if not settings.project_endpoint:
        return None
    roles = load_role_definitions()
    if not roles:
        return None
    factory = (
        client_factory(settings.project_endpoint)
        if client_factory is not None
        else FoundryResponsesClientFactory(
            project_endpoint=settings.project_endpoint,
            credential_factory=default_credential_factory,
        )
    )
    return MafAgentRuntime(
        roles=roles,
        client_factory=factory,
        run_timeout_seconds=FOUNDRY_RUN_TIMEOUT_SECONDS,
    )


def _build_fastapi() -> FastAPI:
    return FastAPI(
        title="Agentic Support Guide API",
        description=(
            "Prototype API demonstrating three collaborating agents. The "
            "coordinator composes each role in-process with Microsoft Agent "
            "Framework and calls Microsoft Foundry models; the same "
            "definitions are also published to Foundry as prompt agents. "
            "Synthetic data only."
        ),
        version=SERVICE_VERSION,
        # FastAPI serves these as plain Starlette routes, outside the router
        # that carries the key check, so on App Service they would hand the
        # full schema to anyone who asked. Local development keeps them: the
        # API is on a laptop and /api/docs is how learners explore it.
        openapi_url=None if running_on_app_service() else "/api/openapi.json",
        docs_url=None if running_on_app_service() else "/api/docs",
        redoc_url=None,
    )


def create_app(
    *,
    runtime: MafAgentRuntime | None = None,
    client_factory: Callable[[str], Any] | None = None,
    evidence_retriever: EvidenceRetriever | None = None,
) -> FastAPI:
    settings = load_foundry_settings()
    app = _build_fastapi()

    # Agent Framework emits every workflow, executor and model span from here on.
    configure_observability(settings.application_insights_connection_string)

    # Explicit allowlist rather than relying on the Vite dev proxy: if this
    # app is ever served directly, no-CORS-middleware means any origin can
    # call it. Credentials are deliberately not allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # FastAPI's default 422 body echoes the rejected value back in `input`,
    # which puts submitted concern text into an HTTP response and any log that
    # records it. Report where the request was wrong, never what was in it.
    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "status": "invalid_request",
                "error_code": "REQUEST_VALIDATION_FAILED",
                "error_message": "The request body did not match the expected shape.",
                "fields": sorted(
                    {".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()}
                ),
            },
        )

    repos = build_repositories()
    plans_store = SavedPlansStore()
    plans_store.seed(
        specs=repos.seeded_plans,
        dealerships=repos.dealerships,
        area_scores=repos.area_scores,
        operations=repos.operations,
        resources=repos.resources,
    )

    setattr(
        app.state,
        STATE_ATTR,
        AppServices(
            settings=settings,
            repos=repos,
            plans_store=plans_store,
            runtime_audit=RuntimeAuditLog(),
            contracts=load_registry(),
            evidence_retriever=(
                evidence_retriever
                if evidence_retriever is not None
                else _build_evidence_retriever()
            ),
            runtime=runtime if runtime is not None else _build_runtime(settings, client_factory),
        ),
    )

    # Each router declares its own "/api" prefix so that `route.path` is the
    # full served path. tests/test_auth.py walks those paths to prove every
    # route carries the API key check, and it can only do that if the prefix
    # is baked in at declaration time rather than applied during matching.
    for module in (health, insights, supports, plans, audit):
        app.include_router(module.router)
    return app


app = create_app()
