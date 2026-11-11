"""The objects `create_app` builds once and every request reads.

Starlette's `app.state` is an untyped attribute bag, so holding the graph in
one dataclass is what lets the dependencies in `dependencies.py` return real
types instead of `Any`. A misspelled attribute is then a type error rather
than an AttributeError on the first request that hits that route.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import AzureFoundrySettings
from .evidence import EvidenceRetriever
from .foundry_agents import MafAgentRuntime
from .plans_store import SavedPlansStore
from .repositories import Repositories
from .runtime_audit import RuntimeAuditLog

STATE_ATTR = "services"


@dataclass
class AppServices:
    """Not frozen: tests swap `settings` and `runtime` on an app they have
    already built."""

    settings: AzureFoundrySettings
    repos: Repositories
    plans_store: SavedPlansStore
    runtime_audit: RuntimeAuditLog
    evidence_retriever: EvidenceRetriever
    runtime: MafAgentRuntime | None
