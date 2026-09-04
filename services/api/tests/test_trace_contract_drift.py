"""Guards agent-trace.schema.json against drift from what the app emits.

The coordinator builds trace steps in Python; the schema is a separate
hand-maintained file. Without this test the two silently diverge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import AgentTraceStep
from app.workflows.coordinator import PROVIDER_ERROR_TO_STATUS

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "v1" / "agent-trace.schema.json"

# Every `agent=` value the coordinator can put on a trace step.
_EMITTED_AGENTS = {
    "evidence-retrieval",
    "data-analyst-agent",
    "support-recommendation-agent",
    "support-recommendation-agent:repair",
    "validator-agent",
}

# Every `status=` value the coordinator can put on a trace step, excluding the
# provider-error statuses derived below.
_EMITTED_STATUSES = {
    "ok",
    "passed",
    "failed",
    "evidence_missing",
    "budget_exhausted",
    "invalid_model_json",
}


def _properties() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    props: dict[str, Any] = schema["properties"]
    return props


def _enum(field: str) -> set[str]:
    values: set[str] = set(_properties()[field]["enum"])
    return values


def test_schema_agent_enum_covers_every_emitted_agent() -> None:
    assert _enum("agent") >= _EMITTED_AGENTS


def test_schema_status_enum_covers_every_emitted_status() -> None:
    provider_statuses = {status for status, _code in PROVIDER_ERROR_TO_STATUS.values()}
    assert _enum("status") >= (_EMITTED_STATUSES | provider_statuses)


def test_schema_declares_every_trace_step_field() -> None:
    assert set(_properties()) >= set(AgentTraceStep.model_fields)
