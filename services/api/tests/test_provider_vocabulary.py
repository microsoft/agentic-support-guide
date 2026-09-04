"""Cross-language guard against stale provider/binding vocabulary.

The provider id is a Python constant, but it is also written into YAML
manifests, TypeScript, PowerShell, and Markdown, none of which can import it.
This test greps those files so a rename cannot silently go half-done.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.foundry_agents import PROVIDER_ID

REPO_ROOT = Path(__file__).resolve().parents[3]

# Vocabulary from the retired persisted-Assistants design.
STALE_TERMS = (
    "azure_foundry_agents",
    "foundry_agents_bound",
    "agent-bindings.local.json",
    "agent-bindings.example.json",
    "sync_foundry_agents",
    "FoundryRemoteAgentAdapter",
    "FoundryAgentClient",
    "sdk_client",
    "remote assistant",
    "--rebind",
)

SCAN_GLOBS = (
    "agents/**/*.yaml",
    "agents/**/*.md",
    "apps/web/src/**/*.ts",
    "apps/web/src/**/*.tsx",
    "scripts/*.ps1",
    "scripts/*.py",
    "services/api/app/**/*.py",
    "*.md",
    "docs/**/*.md",
    "infra/*.md",
    "evals/*.md",
    ".github/workflows/*.yml",
)

EXCLUDE_PARTS = {"node_modules", ".venv", "__pycache__", "dist"}

# ADRs are immutable historical records: 0001/0002 legitimately describe the
# superseded persisted-agent design. A new ADR supersedes them instead.
EXCLUDE_DIRS = ("docs/adr",)


def _scanned_files() -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in SCAN_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file() or EXCLUDE_PARTS & set(path.parts):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(rel.startswith(d) for d in EXCLUDE_DIRS):
                continue
            seen[path] = None
    return list(seen)


@pytest.mark.parametrize("term", STALE_TERMS)
def test_no_stale_persisted_agent_vocabulary(term: str) -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _scanned_files()
        if term in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not offenders, f"stale term {term!r} still present in {offenders}"


def test_provider_id_is_the_expected_value() -> None:
    assert PROVIDER_ID == "azure_foundry_responses"
