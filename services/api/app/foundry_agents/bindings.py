"""Local, gitignored map from agent role -> remote Foundry assistant ID.

The binding file is `.foundry/agent-bindings.local.json` at the repo
root. A committed example lives at `.foundry/agent-bindings.example.json`.

Bindings are refused if the configured project endpoint does not match
the endpoint that produced them (project_endpoint_hash mismatch),
unless the operator passes --rebind on the sync script.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BINDINGS_FILENAME = "agent-bindings.local.json"
EXAMPLE_FILENAME = "agent-bindings.example.json"


class BindingFileError(Exception):
    pass


@dataclass
class AgentBinding:
    role: str
    assistant_id: str
    agent_name: str
    model: str
    instructions_hash: str
    manifest_version: str
    response_format_mode: str
    project_endpoint_hash: str
    updated_at: str
    extra: dict[str, Any] = field(default_factory=dict)


def repo_root() -> Path:
    # services/api/app/foundry_agents/bindings.py -> repo/
    return Path(__file__).resolve().parents[4]


def bindings_path() -> Path:
    return repo_root() / ".foundry" / BINDINGS_FILENAME


def example_path() -> Path:
    return repo_root() / ".foundry" / EXAMPLE_FILENAME


def hash_endpoint(endpoint: str) -> str:
    return hashlib.sha256(endpoint.strip().encode("utf-8")).hexdigest()


def hash_instructions(instructions: str) -> str:
    """Deterministic hash used by tests. The sync script and other
    runtime callers should use `prompt_envelope.instructions_hash`,
    which shares the same normalization. Both are wired to a single
    normalization function so they cannot drift."""
    from .prompt_envelope import instructions_hash as _canonical

    return _canonical(instructions)


def load_bindings() -> dict[str, AgentBinding]:
    path = bindings_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BindingFileError(f"{path.name}: invalid JSON") from exc
    if not isinstance(raw, dict):
        raise BindingFileError(f"{path.name}: root must be an object")
    result: dict[str, AgentBinding] = {}
    for role, obj in raw.items():
        if not isinstance(obj, dict):
            raise BindingFileError(f"{path.name}: {role} entry must be an object")
        result[role] = AgentBinding(
            role=role,
            assistant_id=str(obj.get("assistant_id", "")),
            agent_name=str(obj.get("agent_name", "")),
            model=str(obj.get("model", "")),
            instructions_hash=str(obj.get("instructions_hash", "")),
            manifest_version=str(obj.get("manifest_version", "")),
            response_format_mode=str(obj.get("response_format_mode", "unknown")),
            project_endpoint_hash=str(obj.get("project_endpoint_hash", "")),
            updated_at=str(obj.get("updated_at", "")),
            extra={k: v for k, v in obj.items() if k not in _KNOWN_KEYS},
        )
    return result


def save_bindings(bindings: dict[str, AgentBinding]) -> None:
    """Atomically write the bindings file.

    Writes to a temp file first, then os.replace() into place, so a
    concurrent reader never sees a half-written file and a crash mid-
    write never corrupts the existing file.
    """
    import contextlib
    import os
    import tempfile

    path = bindings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {role: _binding_to_dict(b) for role, b in bindings.items()}
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    # Write to a temp file in the same directory to guarantee same-fs replace.
    fd, tmp_name = tempfile.mkstemp(prefix=".bindings.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _binding_to_dict(b: AgentBinding) -> dict[str, Any]:
    d = asdict(b)
    d.pop("role", None)
    extra = d.pop("extra", {})
    d.update(extra)
    return d


_KNOWN_KEYS = {
    "assistant_id",
    "agent_name",
    "model",
    "instructions_hash",
    "manifest_version",
    "response_format_mode",
    "project_endpoint_hash",
    "updated_at",
}
