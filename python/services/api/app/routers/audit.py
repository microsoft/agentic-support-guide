"""Audit trail: seeded synthetic rows plus this process's real call metadata."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import audit as audit_mod
from ..dependencies import get_audit, get_repos, guarded
from ..models import AuditEvent, AuditResponse
from ..repositories import Repositories
from ..runtime_audit import RuntimeAuditLog

router = APIRouter(prefix="/api")

DISCLAIMER = (
    "Seeded synthetic rows plus in-memory metadata for LLM calls made during "
    "the current process. No prompts, completions, raw validator critique, or "
    "secrets are stored."
)


@router.get("/audit/events", response_model=AuditResponse, dependencies=guarded)
def get_audit_events(
    repos: Repositories = Depends(get_repos),
    audit: RuntimeAuditLog = Depends(get_audit),
) -> AuditResponse:
    seeded = audit_mod.list_events(repos.audit).events
    runtime_rows: list[AuditEvent] = audit.snapshot()
    combined = seeded + runtime_rows
    return AuditResponse(events=combined, total=len(combined), disclaimer=DISCLAIMER)
