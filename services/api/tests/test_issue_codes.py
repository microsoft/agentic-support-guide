"""Issue codes must be a bounded vocabulary, never exception text.

`code = str(exc)` put raw parse-failure text into the trace. Pydantic quotes
the offending value, and that value is model output derived from a
dealer group's evidence. Issue codes travel to the API response and to
Application Insights, so anything free-form there is an exfiltration path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.workflows.failures import invalid_json_code


def _find_issue_code_pattern(node: Any) -> str | None:
    """Locate the issue_codes item pattern anywhere in the schema."""

    if isinstance(node, dict):
        items = node.get("items")
        if isinstance(items, dict) and isinstance(items.get("pattern"), str):
            return str(items["pattern"])
        for value in node.values():
            found = _find_issue_code_pattern(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_issue_code_pattern(value)
            if found:
                return found
    return None


class _Tiny(BaseModel):
    value: int


def _validation_error_quoting(secret: str) -> ValidationError:
    try:
        _Tiny(value=secret)  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def test_decode_failures_get_a_fixed_code() -> None:
    try:
        json.loads("{not json")
    except json.JSONDecodeError as exc:
        assert invalid_json_code(exc) == "AGENT_INVALID_JSON_NOT_JSON"


def test_schema_failures_get_a_fixed_code() -> None:
    exc = _validation_error_quoting("abc")
    assert invalid_json_code(exc) == "AGENT_INVALID_JSON_SCHEMA_MISMATCH"


def test_every_issue_code_satisfies_the_trace_contract() -> None:
    """The published contract restricts issue codes; colons are not allowed.

    An earlier version emitted `AGENT_INVALID_JSON:NOT_JSON`, which would have
    failed validation of the very trace it was describing.
    """

    schema = json.loads(
        (
            Path(__file__).resolve().parents[3] / "contracts" / "v1" / "agent-trace.schema.json"
        ).read_text(encoding="utf-8")
    )
    pattern = _find_issue_code_pattern(schema)
    assert pattern, "could not locate the issue_codes pattern in the contract"

    codes = [
        invalid_json_code(json.JSONDecodeError("x", "y", 0)),
        invalid_json_code(_validation_error_quoting("abc")),
        invalid_json_code(ValueError("anything")),
    ]
    for code in codes:
        assert re.fullmatch(pattern, code), f"{code!r} violates {pattern!r}"


def test_issue_code_never_contains_the_offending_value() -> None:
    secret = "LEARNER-PRIVATE-VALUE-42"
    exc = _validation_error_quoting(secret)
    assert secret in str(exc), "precondition: pydantic quotes the bad value"
    assert secret not in invalid_json_code(exc)


@pytest.mark.parametrize(
    "exc",
    [ValueError("boom with detail"), RuntimeError("also detail")],
)
def test_unknown_failures_fall_back_to_a_fixed_code(exc: Exception) -> None:
    code = invalid_json_code(exc)
    assert code == "AGENT_INVALID_JSON_UNPARSEABLE"
    assert "detail" not in code
