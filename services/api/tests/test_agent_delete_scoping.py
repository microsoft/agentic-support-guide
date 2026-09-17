"""Deleting agents must hit exactly what was named, and nothing else.

`--variant strict --delete` once deleted every agent for the suffix, because
the target set was seeded with the base names and the variant was only ever
added to it. Naming a variant explicitly made the blast radius larger rather
than smaller, which is the opposite of what the flag is for. A learner tidying
up one Module 8 variant lost the whole project.

These assert the target set directly. Nothing here touches Azure.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "publish_prompt_agents.py"


@pytest.fixture(scope="module")
def publisher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_prompt_agents", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _targets(publisher: ModuleType, suffix: str, variants: tuple[str, ...]) -> set[str]:
    """Mirror of the target selection in `_delete_agents`."""
    roles = publisher.ALL_AGENT_DIRS.values()
    if variants:
        out: set[str] = set()
        for variant in variants:
            out |= {publisher._agent_name(role, suffix, variant) for role in roles}
        return out
    return {publisher._agent_name(role, suffix) for role in roles}


def test_variant_delete_does_not_touch_base_agents(publisher: ModuleType) -> None:
    targets = _targets(publisher, "demo", ("strict",))
    base = _targets(publisher, "demo", ())
    assert targets, "variant delete selected nothing"
    assert not (targets & base), (
        f"variant delete would also remove base agents: {sorted(targets & base)}"
    )
    assert all(name.endswith("-strict") for name in targets)


def test_plain_delete_does_not_touch_variants(publisher: ModuleType) -> None:
    base = _targets(publisher, "demo", ())
    assert all(not name.endswith(("-strict", "-baseline")) for name in base)


def test_suffix_match_is_exact_not_prefix(publisher: ModuleType) -> None:
    # Suffixes are single-dash, so `ann` must not select `ann-smith`'s agents.
    assert not (_targets(publisher, "ann", ()) & _targets(publisher, "ann-smith", ()))
