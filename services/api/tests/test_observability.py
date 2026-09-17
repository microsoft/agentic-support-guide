"""Observability comes from Agent Framework instrumentation, not from us.

These tests replace a hand-written recorder and its allowlist. Two properties
mattered then and still matter now:

1. Every node that runs is observable, or the per-agent latency query in
   Module 10 silently omits a step.
2. No prompt, concern text or completion ever leaves the process.

The second is now enforced by Agent Framework (`enable_sensitive_data`
defaults to False) rather than by an allowlist we maintain, so the test is a
canary against that default changing under us.

The provider is configured once for the whole module because OpenTelemetry
refuses to replace a tracer provider that is already set ("Overriding of
current TracerProvider is not allowed") -- reconfiguring per test silently
yields zero spans, and every assertion here would then pass vacuously.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from .conftest import canned_data_analyst_output
from .test_coordinator import _make_coord, _request

pytestmark = pytest.mark.anyio

CANARY = "ZZ-CANARY-CONCERN-TEXT"

# The executors in `app/workflows/graph.py` that run on a passing request.
EXPECTED_EXECUTORS = {
    "retrieve-evidence",
    "data-analyst",
    "support-recommender",
    "validator",
    "finalise",
}


class _Capture(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: object) -> SpanExportResult:
        self.spans.extend(spans)  # type: ignore[arg-type]
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _install() -> _Capture:
    """Configure Agent Framework instrumentation once, through its own API."""

    from agent_framework.observability import (
        configure_otel_providers,
        enable_instrumentation,
    )

    capture = _Capture()
    configure_otel_providers(exporters=[capture])
    enable_instrumentation(force=True)

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider), (
        "Agent Framework did not install an SDK tracer provider; every "
        "assertion in this module would pass on an empty span list."
    )
    return capture


_CAPTURE = _install()


@contextmanager
def _spans() -> Iterator[list[ReadableSpan]]:
    """Collect the spans emitted inside the block."""

    _CAPTURE.spans.clear()
    try:
        yield _CAPTURE.spans
    finally:
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.force_flush()


def _dump(span: ReadableSpan) -> str:
    return json.dumps(
        {
            "name": span.name,
            "attributes": {k: str(v) for k, v in (span.attributes or {}).items()},
            "events": [
                {
                    "name": event.name,
                    "attributes": {k: str(v) for k, v in (event.attributes or {}).items()},
                }
                for event in span.events
            ],
        }
    )


async def test_every_workflow_node_emits_an_executor_span() -> None:
    coord, _ = _make_coord()
    with _spans() as spans:
        result = await coord.run(_request())

    assert result.agent_trace, "the run produced no trace to compare against"

    executor_ids = {
        span.attributes["executor.id"]
        for span in spans
        if span.attributes and "executor.id" in span.attributes
    }
    missing = EXPECTED_EXECUTORS - executor_ids
    assert not missing, f"nodes that ran with no executor span: {sorted(missing)}"


async def test_workflow_run_is_a_span() -> None:
    coord, _ = _make_coord()
    with _spans() as spans:
        await coord.run(_request())

    names = {span.name for span in spans}
    assert "workflow.run" in names
    assert any(name.startswith("executor.process") for name in names)


async def test_no_user_text_reaches_any_span() -> None:
    """The privacy guarantee, asserted against a canary rather than a list."""

    coord, _ = _make_coord()
    with _spans() as spans:
        await coord.run(_request(concern_text=CANARY))

    # Without this the test passes on an empty list and proves nothing.
    assert spans, "no spans captured; this assertion would be vacuous"

    for span in spans:
        assert CANARY not in _dump(span), f"user text leaked into span {span.name}"


async def test_no_model_output_reaches_a_failure_span() -> None:
    """The failure path leaked where the success path did not.

    Agent Framework records the escaping exception on both the executor and
    the workflow span, and a formatted traceback carries the chained cause.
    A Pydantic failure quotes the offending value, which is model output, so
    `StepFailed` is raised `from None` to break the chain.
    """

    bad = json.loads(json.dumps(canned_data_analyst_output()))
    # Longer than the 500-character cap on `detected_need`, so Pydantic
    # rejects it and quotes what it was given.
    bad["analysis"]["detected_need"] = CANARY + "y" * 600

    coord, _ = _make_coord(analyst_payload=bad)
    with _spans() as spans:
        result = await coord.run(_request())

    assert result.status == "invalid_model_json"

    traces = [
        str(dict(event.attributes or {}).get("exception.stacktrace") or "")
        for span in spans
        for event in span.events
        if event.name == "exception"
    ]
    assert traces, "no exception was recorded; this assertion would be vacuous"
    for stacktrace in traces:
        assert CANARY not in stacktrace, "model output leaked into an exception span"
