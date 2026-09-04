"""Build role definitions from agent.md + per-role model deployment env vars.

This replaces the persisted-bindings lookup. A role is available when its
definition file loads and its model deployment environment variable is set -
there is no server-side agent to bind to.
"""

from __future__ import annotations

import os

from .maf_runtime import RoleDefinition
from .prompt_envelope import compose_instructions, load_agent_assets

# Coordinator roles. The hosted three-agent workflow requires all of these.
ROLE_DIRS: dict[str, str] = {
    "data-analyst": "data-analyst-agent",
    "support-recommender": "support-recommendation-agent",
    "validator": "validator-agent",
}

# Standalone workshop agents published to Foundry as prompt agents. They are
# not part of the coordinator, so readiness must not depend on them.
WORKSHOP_AGENT_DIRS: dict[str, str] = {
    "support-explainer": "support-explainer-agent",
}

REQUIRED_ROLES: tuple[str, ...] = tuple(ROLE_DIRS.values())

ALL_AGENT_DIRS: dict[str, str] = {**ROLE_DIRS, **WORKSHOP_AGENT_DIRS}


def model_deployment_env_names(
    dirs: dict[str, str] | None = None,
) -> dict[str, str]:
    """Role -> env var holding its model deployment name."""

    names: dict[str, str] = {}
    for agent_dir, role in (dirs if dirs is not None else ROLE_DIRS).items():
        assets = load_agent_assets(agent_dir)
        foundry = assets.manifest.get("foundry") or {}
        env_name = str(foundry.get("model_deployment_env", "") or "")
        if env_name:
            names[role] = env_name
    return names


def missing_model_deployments() -> list[str]:
    """Env var names a learner still has to populate for the coordinator."""

    return sorted(
        env_name
        for env_name in model_deployment_env_names().values()
        if not os.environ.get(env_name)
    )


def load_agent_definitions(dirs: dict[str, str]) -> dict[str, RoleDefinition]:
    definitions: dict[str, RoleDefinition] = {}
    for agent_dir, role in dirs.items():
        assets = load_agent_assets(agent_dir)
        foundry = assets.manifest.get("foundry") or {}
        env_name = str(foundry.get("model_deployment_env", "") or "")
        deployment = os.environ.get(env_name, "") if env_name else ""
        if not deployment:
            continue
        temperature = foundry.get("temperature")
        definitions[role] = RoleDefinition(
            role=role,
            instructions=compose_instructions(
                assets.agent_md_body, frontmatter=assets.agent_md_frontmatter
            ),
            model_deployment=deployment,
            temperature=float(temperature) if temperature is not None else None,
        )
    return definitions


def load_role_definitions() -> dict[str, RoleDefinition]:
    """Coordinator roles only."""

    return load_agent_definitions(ROLE_DIRS)
