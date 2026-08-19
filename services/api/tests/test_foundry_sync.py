"""Tests for scripts/sync_foundry_agents.py plan/apply logic."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "sync_foundry_agents.py"


def _run_dry_run(env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    for key in (
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_MODEL_DEPLOYMENT_ANALYST",
        "FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER",
        "FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR",
    ):
        env.pop(key, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(  # noqa: S603 - test-controlled command
        [sys.executable, str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


def test_sync_script_dry_run_succeeds_without_network() -> None:
    result = _run_dry_run()
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    # Every agent role appears once in the planned actions block.
    for role in (
        "data-analyst-agent",
        "support-recommendation-agent",
        "validator-agent",
    ):
        assert role in result.stdout, result.stdout


def test_sync_script_dry_run_does_not_print_secrets() -> None:
    result = _run_dry_run()
    combined = result.stdout + result.stderr
    for forbidden in ("Bearer ", "token=", "connection_string=", "key="):
        assert forbidden not in combined, combined
