"""Central schema registry for /contracts/v1.

Loads all JSON Schemas at process start and validates payloads on demand.
The runtime uses this as the sole protocol boundary: every inter-agent
message is validated here before flowing downstream. No relative `$ref`
resolution based on CWD - the registry rewrites in-repo `$ref` values
into a stable in-memory reference before validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

# Repo root is 4 levels up from this file:
# services/api/app/contracts_registry.py -> repo/
_REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = _REPO_ROOT / "contracts" / "v1"


class ContractValidationError(Exception):
    """Raised when a message fails schema validation.

    The message is intentionally short and safe; downstream code must
    never surface raw model output or free-text critique through this
    exception.
    """

    def __init__(self, schema_name: str, safe_reason: str) -> None:
        super().__init__(f"{schema_name}: {safe_reason}")
        self.schema_name = schema_name
        self.safe_reason = safe_reason


@dataclass(frozen=True)
class ContractsRegistry:
    schemas: dict[str, dict[str, Any]]

    def names(self) -> list[str]:
        return sorted(self.schemas.keys())

    def validate(self, schema_name: str, payload: Any) -> None:
        """Validate ``payload`` against the schema and raise on failure."""

        schema = self.schemas.get(schema_name)
        if schema is None:
            raise ContractValidationError(schema_name, "unknown schema")
        try:
            Draft202012Validator(schema).validate(payload)
        except JsonSchemaValidationError as exc:
            # Never echo raw model content; keep the surfaced reason to
            # the JSON pointer path and a short code.
            safe_path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
            raise ContractValidationError(
                schema_name,
                f"validation_failed at {safe_path}",
            ) from None


def load_registry() -> ContractsRegistry:
    """Load and return the registry. Called once at app startup."""

    if not CONTRACTS_DIR.is_dir():
        raise FileNotFoundError(f"contracts directory not found: {CONTRACTS_DIR}")
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(CONTRACTS_DIR.glob("*.schema.json")):
        with path.open(encoding="utf-8") as fh:
            schemas[path.name] = json.load(fh)
    return ContractsRegistry(schemas=schemas)
