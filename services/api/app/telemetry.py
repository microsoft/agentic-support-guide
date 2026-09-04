"""Lightweight telemetry facade.

If APPLICATIONINSIGHTS_CONNECTION_STRING is not set, all calls are no-ops.
No prompt or completion content ever flows through this module.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class TelemetryEvent:
    name: str
    properties: dict[str, Any]


class TelemetryRecorder:
    def __init__(self, connection_string: str | None, max_events: int = 500) -> None:
        self._connection_string = connection_string
        self._events: list[TelemetryEvent] = []
        self._max = max_events
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._connection_string)

    def record(self, name: str, properties: dict[str, Any]) -> None:
        safe = {k: v for k, v in properties.items() if _is_safe_key(k)}
        with self._lock:
            self._events.append(TelemetryEvent(name=name, properties=safe))
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]

    @property
    def events(self) -> list[TelemetryEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> int:
        with self._lock:
            removed = len(self._events)
            self._events = []
            return removed


_UNSAFE_KEYS = {
    "prompt",
    "completion",
    "concern_text",
    "raw_critique",
    "secret",
    "api_key",
    "token",
}


def _is_safe_key(key: str) -> bool:
    return key.lower() not in _UNSAFE_KEYS
