"""Tests for the /agents definitions and remote-agent binding metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.foundry_agents import (
    AGENTS_DIR,
    RUNTIME_ENVELOPE,
    compose_instructions,
    instructions_hash,
    load_agent_assets,
)

AGENT_IDS = ("data-analyst", "support-recommender", "validator")


def test_each_agent_folder_has_required_files() -> None:
    for agent_id in AGENT_IDS:
        agent_dir = AGENTS_DIR / agent_id
        assert agent_dir.is_dir(), f"missing folder /agents/{agent_id}"
        assert (agent_dir / "agent.md").is_file(), f"missing /agents/{agent_id}/agent.md"
        assert (agent_dir / "manifest.yaml").is_file(), f"missing /agents/{agent_id}/manifest.yaml"
        assert (agent_dir / "schemas" / "input.schema.json").is_file()
        assert (agent_dir / "schemas" / "output.schema.json").is_file()


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_manifest_has_required_top_level_keys(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    m = assets.manifest
    assert m.get("id"), f"{agent_id}: missing id"
    assert m.get("version"), f"{agent_id}: missing version"
    assert m.get("runtime"), f"{agent_id}: missing runtime block"
    assert m.get("contracts", {}).get("input"), f"{agent_id}: manifest.contracts.input missing"
    assert m.get("contracts", {}).get("output"), f"{agent_id}: manifest.contracts.output missing"
    assert m.get("handoff"), f"{agent_id}: manifest.handoff missing"
    assert m.get("safety"), f"{agent_id}: manifest.safety missing"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_manifest_has_foundry_binding_block(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    foundry = assets.manifest.get("foundry") or {}
    for key in ("foundry_agent_name", "model_deployment_env", "response_format"):
        assert foundry.get(key), f"{agent_id}: foundry.{key} missing"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_local_schemas_are_valid_json(agent_id: str) -> None:
    for name in ("input.schema.json", "output.schema.json"):
        path = AGENTS_DIR / agent_id / "schemas" / name
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        assert data.get("$schema"), f"{path}: missing $schema"
        assert data.get("type") == "object"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_composed_instructions_include_agent_md_body_and_envelope(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    instructions = compose_instructions(assets.agent_md_body)
    # role-specific content from the Markdown body must appear.
    assert assets.agent_md_body.splitlines()[0] in instructions
    assert RUNTIME_ENVELOPE.strip() in instructions


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_instructions_hash_is_stable_across_whitespace(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    ihash1 = instructions_hash(compose_instructions(assets.agent_md_body))
    # Same body with different line-ending style should hash identically.
    crlf_body = assets.agent_md_body.replace("\n", "\r\n")
    ihash2 = instructions_hash(compose_instructions(crlf_body))
    assert ihash1 == ihash2


def test_python_source_has_no_hardcoded_role_prompt() -> None:
    """No role-specific prompt text should live in Python."""

    forbidden_signals = (
        "You are the Data Analyst Agent",
        "You are the Support Recommendation Agent",
        "You are the Validator Agent",
    )
    py_root = Path(__file__).resolve().parents[1] / "app"
    for py_file in py_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for signal in forbidden_signals:
            assert signal not in text, (
                f"{py_file}: contains hardcoded role prompt '{signal}'. "
                "Role instructions must live in /agents/<id>/agent.md."
            )


def test_agents_do_not_import_each_other() -> None:
    """Enforce the independence rule from the architecture."""

    agents_root = Path(__file__).resolve().parents[1] / "app" / "agents"
    for py in agents_root.rglob("agent.py"):
        text = py.read_text(encoding="utf-8")
        for forbidden in (
            "from ..data_analyst",
            "from ..support_recommender",
            "from ..validator",
        ):
            assert (
                forbidden not in text
            ), f"{py}: cross-agent import '{forbidden}' violates independence."


def test_agents_do_not_import_api_internals() -> None:
    """/agents Python modules must not depend on API routing, models, or workflows."""

    agents_root = Path(__file__).resolve().parents[1] / "app" / "agents"
    for py in agents_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for forbidden in (
            "from ..main",
            "from ..workflows",
            "from ..models",
            "from ..plans_store",
            "from ..runtime_audit",
        ):
            assert forbidden not in text, f"{py}: forbidden API-internals import '{forbidden}'."


def test_no_direct_model_calls_outside_sdk_client() -> None:
    """No app-code file (except the SDK client wrapper) may import openai
    or reference AzureOpenAI / chat.completions. This asserts that the
    recommendation path goes through the remote-agent adapter only.
    """

    py_root = Path(__file__).resolve().parents[1] / "app"
    forbidden = ("AzureOpenAI", "openai.", "chat.completions")
    permitted = (
        # The wrapper file exists in the foundry_agents package if we ever
        # add one that talks to the base model directly. Today the SDK
        # wrapper only uses azure-ai-agents; keep the allowlist here so
        # future direct-model helpers can be quarantined.
        py_root / "foundry_agents" / "sdk_client.py",
    )
    for py_file in py_root.rglob("*.py"):
        if py_file in permitted:
            continue
        text = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, (
                f"{py_file}: forbidden reference to '{token}'. "
                "All model calls must go through the Foundry remote adapter."
            )


def test_all_manifests_load_via_yaml() -> None:
    """Belt-and-suspenders: every manifest.yaml round-trips through yaml.safe_load."""
    for agent_id in AGENT_IDS:
        text = (AGENTS_DIR / agent_id / "manifest.yaml").read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        assert isinstance(data, dict)
