"""Runtime audit metadata store.

Runtime rows are metadata only: agent name, endpoint, provider/model,
duration, token estimate, status, correlation_id, district_id, evidence
counts, validator status. Never prompts, completions, secrets, or raw
concern text.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from .human_review import ReviewTransitionAuditEntry
from .models import AuditEvent


class RuntimeAuditLog:
    def __init__(self, max_rows: int = 500) -> None:
        self._rows: list[AuditEvent] = []
        self._lock = threading.Lock()
        self._max = max_rows
        self._counter = 0

    def append(
        self,
        *,
        endpoint: str,
        context: str,
        provider_model: str,
        duration_ms: int,
        token_estimate: int,
        status: str,
        user: str = "S-01",
        correlation_id: str = "",
        district_id: str = "",
        evidence_count: int = 0,
        citation_count: int = 0,
        validator_status: str = "",
    ) -> None:
        with self._lock:
            self._counter += 1
            self._rows.append(
                AuditEvent(
                    event_id=f"AUD-R{self._counter:05d}",
                    timestamp=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    endpoint=endpoint,
                    context=context,
                    user=user,
                    provider_model=provider_model,
                    duration_ms=duration_ms,
                    token_estimate=token_estimate,
                    status=status,
                    correlation_id=correlation_id,
                    district_id=district_id,
                    evidence_count=evidence_count,
                    citation_count=citation_count,
                    validator_status=validator_status,
                )
            )
            if len(self._rows) > self._max:
                self._rows = self._rows[-self._max :]

    def append_review_transition(self, entry: ReviewTransitionAuditEntry) -> None:
        """Record a human-review state transition as a safe audit row."""

        with self._lock:
            self._counter += 1
            self._rows.append(
                AuditEvent(
                    event_id=f"AUD-R{self._counter:05d}",
                    timestamp=entry.timestamp,
                    endpoint="/api/supports/plans/{plan_id}/review",
                    context=f"review:{entry.previous_state}->{entry.new_state}",
                    user=entry.user_label,
                    provider_model="human-review",
                    duration_ms=0,
                    token_estimate=0,
                    status=entry.new_state,
                    correlation_id=entry.correlation_id,
                    district_id=entry.district_id,
                    evidence_count=entry.evidence_count,
                    citation_count=0,
                    validator_status=entry.validator_verdict,
                )
            )
            if len(self._rows) > self._max:
                self._rows = self._rows[-self._max :]

    def snapshot(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> int:
        with self._lock:
            removed = len(self._rows)
            self._rows = []
            self._counter = 0
            return removed
