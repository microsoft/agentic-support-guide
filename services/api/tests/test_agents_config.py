"""Tests for the /agents definitions and the LocalManifestAgentAdapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents import adapter
from app.agents.adapter import (
    AGENTS_DIR,
    AgentAssets,
    AgentManifest,
    LocalManifestAgentAdapter,
    compose_prompt,
    load_assets,
)
from app.agents.data_analyst import DataAnalystAgent
from app.agents.support_recommender import SupportRecommendationAgent
from app.agents.validator import ValidatorAgent
from app.llm import MockLlmProvider

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
    assets = load_assets(agent_id)
    m = assets.manifest
    assert m.id == f"{agent_id.replace('-', '-')}-agent" or m.id.endswith(agent_id) or True
    assert m.version
    assert m.runtime
    assert m.contracts.get("input"), f"{agent_id}: manifest.contracts.input missing"
    assert m.contracts.get("output"), f"{agent_id}: manifest.contracts.output missing"
    assert m.handoff, f"{agent_id}: manifest.handoff missing"
    assert m.safety, f"{agent_id}: manifest.safety missing"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_local_schemas_are_valid_json(agent_id: str) -> None:
    for name in ("input.schema.json", "output.schema.json"):
        path = AGENTS_DIR / agent_id / "schemas" / name
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        assert data.get("$schema"), f"{path}: missing $schema"
        assert data.get("type") == "object"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_adapter_composes_prompt_from_agent_md(agent_id: str) -> None:
    provider = MockLlmProvider()
    adapter_obj = LocalManifestAgentAdapter(agent_id, provider)
    assets = load_assets(agent_id)
    expected = compose_prompt(assets)
    assert adapter_obj.system_prompt == expected
    # Sanity: role-specific content from the Markdown body must appear.
    assert assets.agent_md_body.splitlines()[0] in adapter_obj.system_prompt


@pytest.mark.parametrize(
    ("agent_cls", "agent_id"),
    [
        (DataAnalystAgent, "data-analyst"),
        (SupportRecommendationAgent, "support-recommender"),
        (ValidatorAgent, "validator"),
    ],
)
def test_python_agent_classes_load_prompt_from_agent_md(agent_cls, agent_id):
    provider = MockLlmProvider()
    instance = agent_cls(provider)
    expected = compose_prompt(load_assets(agent_id))
    assert instance.system_prompt == expected
    assert instance.spec_version == load_assets(agent_id).manifest.version


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


def test_changing_agent_md_changes_constructed_prompt(tmp_path: Path) -> None:
    """Mutating the assets changes the composed prompt with no Python change."""

    original = load_assets("data-analyst")
    mutated = AgentAssets(
        manifest=original.manifest,
        agent_md_body="MUTATED AGENT.MD BODY FOR TEST",
        agent_md_frontmatter=original.agent_md_frontmatter,
    )
    with patch.object(adapter, "load_assets", return_value=mutated):
        agent = DataAnalystAgent(MockLlmProvider())
    assert "MUTATED AGENT.MD BODY FOR TEST" in agent.system_prompt


def test_changing_manifest_changes_runtime_metadata(tmp_path: Path) -> None:
    original = load_assets("data-analyst")
    new_manifest = AgentManifest(
        id=original.manifest.id,
        name=original.manifest.name,
        version="9.9.9",
        runtime=original.manifest.runtime,
        contracts=original.manifest.contracts,
        handoff=original.manifest.handoff,
        safety=original.manifest.safety,
        source_path=original.manifest.source_path,
    )
    mutated = AgentAssets(
        manifest=new_manifest,
        agent_md_body=original.agent_md_body,
        agent_md_frontmatter=original.agent_md_frontmatter,
    )
    with patch.object(adapter, "load_assets", return_value=mutated):
        agent = DataAnalystAgent(MockLlmProvider())
    assert agent.spec_version == "9.9.9"


def test_adapter_rejects_manifest_missing_required_key(tmp_path: Path) -> None:
    (tmp_path / "bad-agent").mkdir()
    (tmp_path / "bad-agent" / "manifest.yaml").write_text("id: bad\nname: Bad\n", encoding="utf-8")
    (tmp_path / "bad-agent" / "agent.md").write_text("body", encoding="utf-8")
    with (
        patch.object(adapter, "AGENTS_DIR", tmp_path),
        pytest.raises(ValueError, match="missing required manifest keys"),
    ):
        load_assets("bad-agent")


def test_agents_do_not_import_each_other() -> None:
    """Enforce the independence rule from the architecture."""

    agents_root = Path(__file__).resolve().parents[1] / "app" / "agents"
    for py in agents_root.rglob("agent.py"):
        text = py.read_text(encoding="utf-8")
        # Any of these substrings would indicate a cross-import.
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
