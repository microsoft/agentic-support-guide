"""Runtime audit metadata store.

Runtime rows are metadata only: agent name, endpoint, provider/model,
duration, token estimate, status. Never prompts, completions, secrets, or
raw concern text.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

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
