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
        assert agent_dir.is_dir()
        assert (agent_dir / "agent.md").is_file()
        assert (agent_dir / "manifest.yaml").is_file()
        assert (agent_dir / "schemas" / "input.schema.json").is_file()
        assert (agent_dir / "schemas" / "output.schema.json").is_file()


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_manifest_has_required_top_level_keys(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    m = assets.manifest
    assert m.get("id")
    assert m.get("version")
    assert m.get("runtime")
    assert m.get("contracts", {}).get("input")
    assert m.get("contracts", {}).get("output")
    assert m.get("handoff")
    assert m.get("safety")


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_manifest_has_foundry_runtime_block(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    foundry = assets.manifest.get("foundry") or {}
    for key in ("model_deployment_env", "response_format"):
        assert foundry.get(key), f"{agent_id}: foundry.{key} missing"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_manifest_has_no_persisted_agent_name(agent_id: str) -> None:
    """Published names are learner-suffixed at publish time, never in the manifest."""

    assets = load_agent_assets(agent_id)
    foundry = assets.manifest.get("foundry") or {}
    assert "foundry_agent_name" not in foundry


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_local_schemas_are_valid_json(agent_id: str) -> None:
    for name in ("input.schema.json", "output.schema.json"):
        path = AGENTS_DIR / agent_id / "schemas" / name
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        assert data.get("$schema")
        assert data.get("type") == "object"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_composed_instructions_include_agent_md_body_and_envelope(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    instructions = compose_instructions(
        assets.agent_md_body, frontmatter=assets.agent_md_frontmatter
    )
    assert assets.agent_md_body.splitlines()[0] in instructions
    assert RUNTIME_ENVELOPE.strip() in instructions


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_composed_instructions_carry_frontmatter_rules(agent_id: str) -> None:
    """The output contract lives in frontmatter; dropping it yields off-contract JSON."""

    assets = load_agent_assets(agent_id)
    instructions = compose_instructions(
        assets.agent_md_body, frontmatter=assets.agent_md_frontmatter
    )
    for key in ("constraints", "safety_rules", "grounding_rules"):
        for item in assets.agent_md_frontmatter.get(key) or []:
            assert str(item).strip() in instructions, f"{agent_id}: dropped {key} -> {item}"


def test_data_analyst_instructions_state_the_output_shape() -> None:
    assets = load_agent_assets("data-analyst")
    instructions = compose_instructions(
        assets.agent_md_body, frontmatter=assets.agent_md_frontmatter
    )
    for token in ("contract_version", "analysis", "detected_need", "evidence_bullets"):
        assert token in instructions


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_instructions_hash_is_stable_across_whitespace(agent_id: str) -> None:
    assets = load_agent_assets(agent_id)
    ihash1 = instructions_hash(
        compose_instructions(assets.agent_md_body, frontmatter=assets.agent_md_frontmatter)
    )
    crlf_body = assets.agent_md_body.replace("\n", "\r\n")
    ihash2 = instructions_hash(
        compose_instructions(crlf_body, frontmatter=assets.agent_md_frontmatter)
    )
    assert ihash1 == ihash2


def test_python_source_has_no_hardcoded_role_prompt() -> None:
    forbidden_signals = (
        "You are the Data Analyst Agent",
        "You are the Support Recommendation Agent",
        "You are the Validator Agent",
    )
    py_root = Path(__file__).resolve().parents[1] / "app"
    for py_file in py_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for signal in forbidden_signals:
            assert signal not in text


def test_agents_do_not_import_each_other() -> None:
    agents_root = Path(__file__).resolve().parents[1] / "app" / "agents"
    for py in agents_root.rglob("agent.py"):
        text = py.read_text(encoding="utf-8")
        for forbidden in (
            "from ..data_analyst",
            "from ..support_recommender",
            "from ..validator",
        ):
            assert forbidden not in text


def test_agents_do_not_import_api_internals() -> None:
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
            assert forbidden not in text


def test_no_direct_model_calls_outside_sdk_client() -> None:
    py_root = Path(__file__).resolve().parents[1] / "app"
    forbidden = ("AzureOpenAI", "openai.", "chat.completions")
    permitted = (py_root / "foundry_agents" / "sdk_client.py",)
    for py_file in py_root.rglob("*.py"):
        if py_file in permitted:
            continue
        text = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{py_file}: forbidden reference to '{token}'"


def test_all_manifests_load_via_yaml() -> None:
    for agent_id in AGENT_IDS:
        text = (AGENTS_DIR / agent_id / "manifest.yaml").read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        assert isinstance(data, dict)
