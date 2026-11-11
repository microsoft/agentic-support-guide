"""FastAPI dependencies.

Each one pulls a single object out of the `AppServices` container that
`create_app` put on `app.state`. Keeping them here rather than nested inside
`create_app` is what lets the routers live in their own modules.
"""

from __future__ import annotations

from typing import cast

from fastapi import Depends, Request

from .auth import require_api_key
from .config import AzureFoundrySettings
from .contracts_registry import ContractsRegistry
from .evidence import EvidenceRetriever
from .foundry_agents import MafAgentRuntime
from .plans_store import SavedPlansStore
from .repositories import Repositories
from .runtime_audit import RuntimeAuditLog
from .services import STATE_ATTR, AppServices

# `/api/health` is the only anonymous route: deploy-app.ps1 and CI poll it to
# find out which build is serving, and that runs before the web tier is up.
# Everything else, including `/health/details`, needs the key.
guarded = [Depends(require_api_key)]


def get_services(request: Request) -> AppServices:
    """The one untyped hop. Every accessor below it is checked."""

    return cast(AppServices, getattr(request.app.state, STATE_ATTR))


def get_settings(request: Request) -> AzureFoundrySettings:
    return get_services(request).settings


def get_runtime(request: Request) -> MafAgentRuntime | None:
    return get_services(request).runtime


def get_repos(request: Request) -> Repositories:
    return get_services(request).repos


def get_plans(request: Request) -> SavedPlansStore:
    return get_services(request).plans_store


def get_audit(request: Request) -> RuntimeAuditLog:
    return get_services(request).runtime_audit


def get_contracts(request: Request) -> ContractsRegistry:
    return get_services(request).contracts


def get_evidence(request: Request) -> EvidenceRetriever:
    return get_services(request).evidence_retriever
