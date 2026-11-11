"""Observability, entirely from Microsoft Agent Framework.

There is no recorder and no custom event schema here. `enable_instrumentation`
makes Agent Framework emit OpenTelemetry spans for everything it runs:

    workflow.build            the graph, with its full definition as JSON
    workflow.run              one request end to end
    executor.process <id>     one node, e.g. `executor.process support-recommender`
    edge_group.process        an edge firing, with its delivery status
    chat / invoke_agent       one model call, with gen_ai.* attributes:
                              response model, input/output tokens, error type

That is a superset of the hand-written recorder this replaced, which kept a
bounded in-memory list and exported an allowlisted subset through a logger.

Prompt and completion text stays out because `enable_sensitive_data` defaults
to False. Never call `enable_sensitive_telemetry()` in this app; the workshop
runs on a shared subscription and a span is forever.

https://learn.microsoft.com/agent-framework/tutorials/observability
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.sdk._logs.export import LogRecordExporter
    from opentelemetry.sdk.metrics.export import MetricExporter
    from opentelemetry.sdk.trace.export import SpanExporter

_LOGGER = logging.getLogger(__name__)

_lock = threading.Lock()
_configured = False


def configure_observability(connection_string: str | None) -> bool:
    """Turn on Agent Framework instrumentation. Returns True when exporting.

    Idempotent and never fatal: telemetry must not be able to stop the app
    from serving.

    Without a connection string this is close to a no-op. Agent Framework
    only installs an SDK tracer provider when it is given an exporter, so
    with none the global provider stays the no-op proxy and no spans are
    produced at all. That is the right default for local runs and tests.
    """

    global _configured
    with _lock:
        if _configured:
            return bool(connection_string)
        try:
            from agent_framework.observability import (
                configure_otel_providers,
                enable_instrumentation,
            )

            exporters: list[LogRecordExporter | SpanExporter | MetricExporter] = []
            if connection_string:
                from azure.monitor.opentelemetry.exporter import (
                    AzureMonitorLogExporter,
                    AzureMonitorTraceExporter,
                )

                exporters = [
                    AzureMonitorTraceExporter(connection_string=connection_string),
                    AzureMonitorLogExporter(connection_string=connection_string),
                ]

            configure_otel_providers(exporters=exporters or None)
            enable_instrumentation()
            _configured = True
        except Exception:  # noqa: BLE001 - telemetry must never break a request
            _LOGGER.debug("Agent Framework instrumentation unavailable", exc_info=True)
            return False
        return bool(connection_string)
