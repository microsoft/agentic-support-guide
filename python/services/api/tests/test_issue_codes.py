"""Issue codes must be a bounded vocabulary, never exception text.

`code = str(exc)` put raw parse-failure text into the trace. Pydantic quotes
the offending value, and that value is model output derived from a
dealer group's evidence. Issue codes travel to the API response and to
Application Insights, so anything free-form there is an exfiltration path.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.shared.prompt_blocks import CODE_REGEX
from app.workflows.failures import invalid_json_code


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


def test_every_issue_code_satisfies_the_code_format() -> None:
    """Issue codes are uppercase snake case; colons are not allowed.

    An earlier version emitted `AGENT_INVALID_JSON:NOT_JSON`, which broke the
    very format it was describing.
    """

    codes = [
        invalid_json_code(json.JSONDecodeError("x", "y", 0)),
        invalid_json_code(_validation_error_quoting("abc")),
        invalid_json_code(ValueError("anything")),
    ]
    for code in codes:
        assert CODE_REGEX.fullmatch(code), f"{code!r} violates {CODE_REGEX.pattern!r}"


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
