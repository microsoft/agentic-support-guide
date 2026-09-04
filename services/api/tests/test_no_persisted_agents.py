"""Guards that the runtime never uses the retired Assistants API.

Legacy `asst_*` assistants are what triggered the Foundry portal's
"Update your agents" migration banner. Prompt agents published through
`AIProjectClient.agents.create_version` are Foundry's current model and are
fine - they render natively in the portal with no banner.

So this guard bans the legacy path, not agent publishing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = (
    REPO_ROOT / "services" / "api" / "app",
    REPO_ROOT / "scripts",
)

# Retired Assistants-API surface.
FORBIDDEN_SYMBOLS = ("AgentsClient", "azure.ai.agents")

# Assistants CRUD. `create_version` is deliberately absent: that is the
# current prompt-agent API.
FORBIDDEN_CALLS = ("create_agent(", "update_agent(", "delete_agent(")

# Publishing prompt agents is allowed only from this script, so the runtime
# request path can never accidentally create a resource.
PUBLISH_ALLOWLIST = {"scripts/publish_prompt_agents.py"}
PUBLISH_SYMBOLS = ("to_prompt_agent", "create_version(")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _code_lines(path: Path) -> list[str]:
    """Lines excluding comments, so prose naming these symbols doesn't trip the guard."""

    out: list[str] = []
    in_doc = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        quotes = line.count('"""') + line.count("'''")
        if in_doc:
            if quotes:
                in_doc = False
            continue
        if line.startswith(('"""', "'''")):
            if quotes < 2:
                in_doc = True
            continue
        if line.startswith("#"):
            continue
        out.append(line)
    return out


@pytest.mark.parametrize("symbol", FORBIDDEN_SYMBOLS)
def test_legacy_assistants_api_is_never_imported(symbol: str) -> None:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _python_files()
        if any(pattern.search(line) for line in _code_lines(path))
    ]
    assert not offenders, f"{symbol} is the retired Assistants API; found in {offenders}"


@pytest.mark.parametrize("call", FORBIDDEN_CALLS)
def test_assistants_crud_calls_are_absent(call: str) -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _python_files()
        if any(call in line for line in _code_lines(path))
    ]
    assert not offenders, f"{call} is Assistants-API CRUD; found in {offenders}"


@pytest.mark.parametrize("symbol", PUBLISH_SYMBOLS)
def test_agent_publishing_stays_out_of_the_request_path(symbol: str) -> None:
    """Publishing is a GenAIOps step, never something a web request triggers."""

    offenders = [
        rel
        for path in _python_files()
        if (rel := path.relative_to(REPO_ROOT).as_posix()) not in PUBLISH_ALLOWLIST
        and any(symbol in line for line in _code_lines(path))
    ]
    assert not offenders, f"{symbol} may only be used by the publish script; found in {offenders}"
