"""Telemetry facade with optional Application Insights export.

Events are always kept in a bounded in-memory ring so tests stay offline.
When APPLICATIONINSIGHTS_CONNECTION_STRING is set they are ALSO exported,
which is what makes Module 9's KQL queries return rows. Before that,
`record()` only appended to a list, so the connection string was configured,
the module told learners to query Application Insights, and every query came
back empty.

No prompt or completion content flows through this module. Exported
properties are restricted by an allowlist rather than a denylist, because a
denylist silently exports whatever field a future caller happens to add.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger("agentic_support_guide.telemetry")
# Left at NOTSET this inherits the root level, which uvicorn leaves at WARNING,
# so `_LOGGER.info(...)` never creates a record and nothing is ever exported.
# `configure_azure_monitor` attaches a handler but does not set a level. Set
# here rather than inside the exporter so emission never depends on
# configuration order. Records are still only produced when export is on.
_LOGGER.setLevel(logging.INFO)

# Only these leave the process. Anything else stays in memory.
EXPORTABLE_KEYS = frozenset(
    {
        "agent",
        "citation_count",
        "code",
        "correlation_id",
        "district_id",
        "evidence_count",
        "issue_codes",
        "latency_ms",
        "model",
        "provider",
        "provider_model",
        "status",
        "token_estimate",
        "validator_status",
    }
)

_configured = False
_configure_lock = threading.Lock()


def _configure_exporter(connection_string: str) -> bool:
    """Configure Azure Monitor once per process. Never fatal."""

    global _configured
    with _configure_lock:
        if _configured:
            return True
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=connection_string,
                logger_name=_LOGGER.name,
            )
            _configured = True
        except Exception:  # noqa: BLE001 - telemetry must never break a request
            _LOGGER.debug("Application Insights export unavailable", exc_info=True)
            return False
        return True


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
        self._exporting = _configure_exporter(connection_string) if connection_string else False

    @property
    def enabled(self) -> bool:
        return bool(self._connection_string)

    @property
    def exporting(self) -> bool:
        """True when events actually reach Application Insights."""

        return self._exporting

    def record(self, name: str, properties: dict[str, Any]) -> None:
        safe = {k: v for k, v in properties.items() if _is_safe_key(k)}
        with self._lock:
            self._events.append(TelemetryEvent(name=name, properties=safe))
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]
        if self._exporting:
            self._export(name, safe)

    def _export(self, name: str, safe: dict[str, Any]) -> None:
        payload = {
            key: _stringify(value)
            for key, value in safe.items()
            if key in EXPORTABLE_KEYS and value is not None
        }
        payload["event_name"] = name
        try:
            # Lands in the `traces` table with these under customDimensions,
            # which is what Module 9's queries filter on.
            _LOGGER.info(name, extra=payload)
        except Exception:  # noqa: BLE001 - telemetry must never break a request
            _LOGGER.debug("telemetry export failed", exc_info=True)

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


def _stringify(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ",".join(str(v) for v in value)
    return str(value)


def _is_safe_key(key: str) -> bool:
    return key.lower() not in _UNSAFE_KEYS
