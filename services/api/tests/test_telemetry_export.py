"""Telemetry must export operational fields and nothing else.

Exporting to Application Insights is what makes Module 9 real, but it also
moves data out of the process, so the boundary needs a test rather than a
comment. The allowlist exists because a denylist silently exports whatever
field a future caller adds.
"""

from __future__ import annotations

import logging

import pytest

from app.telemetry import EXPORTABLE_KEYS, TelemetryRecorder


def test_unconfigured_recorder_does_not_export() -> None:
    recorder = TelemetryRecorder(None)
    assert recorder.enabled is False
    assert recorder.exporting is False
    recorder.record("evidence_retrieval", {"correlation_id": "abc"})
    assert len(recorder.events) == 1


def test_records_are_kept_in_memory_even_without_export() -> None:
    recorder = TelemetryRecorder(None)
    recorder.record("agent_call", {"agent": "validator-agent", "latency_ms": 12})
    event = recorder.events[-1]
    assert event.name == "agent_call"
    assert event.properties["agent"] == "validator-agent"


def test_prompt_text_never_reaches_the_recorder() -> None:
    recorder = TelemetryRecorder(None)
    recorder.record(
        "agent_call",
        {
            "correlation_id": "abc",
            "concern_text": "a learner's private concern",
            "prompt": "system prompt",
            "completion": "model output",
        },
    )
    stored = recorder.events[-1].properties
    assert "concern_text" not in stored
    assert "prompt" not in stored
    assert "completion" not in stored


def test_export_payload_is_restricted_to_the_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anything outside EXPORTABLE_KEYS must stay in the process.

    Deliberately does NOT use `caplog.at_level`. Forcing the level hides the
    thing that matters: with the logger left at NOTSET it inherits root
    (WARNING under uvicorn), `info()` never creates a record, and nothing is
    exported. A test that raises the level itself passes against a dead
    production path.
    """

    captured: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    logger = logging.getLogger("agentic_support_guide.telemetry")
    handler = Capture()
    logger.addHandler(handler)
    monkeypatch.setattr(logging.getLogger(), "level", logging.WARNING)
    try:
        recorder = TelemetryRecorder(None)
        monkeypatch.setattr(recorder, "_exporting", True)
        recorder.record(
            "agent_call",
            {
                "correlation_id": "corr-1",
                "district_id": "DIST-A",
                "latency_ms": 42,
                # Not in the allowlist: operational-looking but unreviewed.
                "learner_id": "LRN-0001",
                "internal_note": "should not leave the process",
            },
        )
    finally:
        logger.removeHandler(handler)

    assert captured, (
        "no record was emitted: the telemetry logger level is not set, so "
        "nothing reaches Application Insights"
    )
    emitted = vars(captured[-1])
    assert emitted["correlation_id"] == "corr-1"
    assert emitted["district_id"] == "DIST-A"
    assert "learner_id" not in emitted
    assert "internal_note" not in emitted


def test_allowlist_excludes_free_text_fields() -> None:
    for forbidden in ("concern_text", "prompt", "completion", "learner_id", "raw_critique"):
        assert forbidden not in EXPORTABLE_KEYS
