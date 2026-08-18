"""Lightweight telemetry facade.

If APPLICATIONINSIGHTS_CONNECTION_STRING is not set, all calls are no-ops.
No prompt or completion content ever flows through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TelemetryEvent:
    name: str
    properties: dict[str, Any]


class TelemetryRecorder:
    def __init__(self, connection_string: str | None) -> None:
        self._connection_string = connection_string
        self._events: list[TelemetryEvent] = []

    @property
    def enabled(self) -> bool:
        return bool(self._connection_string)

    def record(self, name: str, properties: dict[str, Any]) -> None:
        safe = {k: v for k, v in properties.items() if _is_safe_key(k)}
        self._events.append(TelemetryEvent(name=name, properties=safe))

    @property
    def events(self) -> list[TelemetryEvent]:
        return list(self._events)


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
