"""Read a role response as a validated model.

`response_format` makes the provider return a parsed object on
`AgentResponse.value`. Not every model deployment supports strict structured
output, so fall back to parsing the raw text rather than hard-failing a
learner whose deployment lacks the feature.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from ...foundry_agents.maf_runtime import RoleResponse


def parse_role_response[T: BaseModel](response: RoleResponse, model: type[T]) -> T:
    """Return the response as `model`, or raise ValueError with a stable code."""

    parsed = response.parsed
    if isinstance(parsed, model):
        return parsed

    if parsed is not None:
        try:
            return model.model_validate(parsed if isinstance(parsed, dict) else parsed.__dict__)
        except (ValidationError, AttributeError, TypeError) as exc:
            raise ValueError("invalid_model_schema") from exc

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_model_json") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("invalid_model_schema") from exc
