"""Audit event view - seeded synthetic events only, not live request logs."""

from __future__ import annotations

from .mock_data import AuditRow
from .models import AuditEvent, AuditResponse

DISCLAIMER = (
    "Synthetic audit rows only. No real AI or cloud calls occurred. "
    "Provider/model labels are placeholders."
)


def list_events(rows: list[AuditRow]) -> AuditResponse:
    events = [
        AuditEvent(
            event_id=r.event_id,
            timestamp=r.timestamp,
            endpoint=r.endpoint,
            context=r.context,
            user=r.user,
            provider_model=r.provider_model,
            duration_ms=r.duration_ms,
            token_estimate=r.token_estimate,
            status=r.status,
        )
        for r in rows
    ]
    return AuditResponse(events=events, total=len(events), disclaimer=DISCLAIMER)
