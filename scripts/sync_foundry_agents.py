#!/usr/bin/env python
"""Sync /agents/<id>/ definitions to remote Azure AI Foundry agents.

This script is the only way remote agents get created or updated. It
reads /agents/<id>/agent.md and manifest.yaml, composes the runtime
instructions (agent.md body + fixed runtime envelope), computes a
sha256 hash of the normalized instructions, and reconciles that
against the local binding file `.foundry/agent-bindings.local.json`.

Modes:
    --dry-run          Read manifests, plan actions. No network.
    --apply            Create or update remote agents. Writes bindings file.
    --check-connectivity
                       Instantiate the Foundry client and call a cheap
                       list operation to validate endpoint + RBAC.
    --rebind           Ignore the project_endpoint_hash guard when the
                       binding file was produced against a different
                       Foundry project endpoint. Use when moving
                       between environments.

Never prints tokens, endpoints, prompts, or completions. Missing
credentials are surfaced as safe messages.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.foundry_agents import (  # noqa: E402
    AgentBinding,
    ConfigurationError,
    FoundryAgentClient,
    FoundryAgentClientProtocol,
    FoundryProviderError,
    compose_instructions,
    hash_endpoint,
    instructions_hash,
    load_agent_assets,
    load_bindings,
    save_bindings,
)
from app.foundry_agents.bindings import bindings_path, example_path  # noqa: E402

AGENTS_DIR = REPO_ROOT / "agents"
CONTRACTS_DIR = REPO_ROOT / "contracts" / "v1"

REQUIRED_MANIFEST_KEYS = ("id", "name", "version", "runtime", "contracts", "handoff", "safety")
REQUIRED_FOUNDRY_KEYS = ("foundry_agent_name", "model_deployment_env", "response_format")
REQUIRED_CONTRACT_SIDES = ("input", "output")
REQUIRED_CONTRACT_KEYS = ("schema_ref", "schema_version")


@dataclass(frozen=True)
class PlannedAction:
    role: str
    action: str  # "create", "update", "skip"
    agent_name: str
    model_deployment_env: str
    instructions_hash: str
    reason: str


def _validate_manifest(agent_dir: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    manifest_path = agent_dir / "manifest.yaml"
    md_path = agent_dir / "agent.md"
    if not manifest_path.is_file():
        errors.append(f"{agent_dir.name}: missing manifest.yaml")
        return {}, errors
    if not md_path.is_file():
        errors.append(f"{agent_dir.name}: missing agent.md")

    assets = load_agent_assets(agent_dir.name)
    manifest = assets.manifest

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            errors.append(f"{agent_dir.name}: manifest missing required key '{key}'")

    foundry = manifest.get("foundry") or {}
    for key in REQUIRED_FOUNDRY_KEYS:
        if key not in foundry:
            errors.append(f"{agent_dir.name}: foundry.{key} missing")

    contracts = manifest.get("contracts") or {}
    for side in REQUIRED_CONTRACT_SIDES:
        block = contracts.get(side) or {}
        for key in REQUIRED_CONTRACT_KEYS:
            if key not in block:
                errors.append(f"{agent_dir.name}: contracts.{side}.{key} missing")

    for side in REQUIRED_CONTRACT_SIDES:
        block = contracts.get(side) or {}
        ref = block.get("schema_ref")
        if ref and not (CONTRACTS_DIR / ref).is_file():
            errors.append(
                f"{agent_dir.name}: contracts.{side}.schema_ref not found "
                f"in /contracts/v1 -> {ref}"
            )

    for handoff in manifest.get("handoff") or []:
        contract = handoff.get("contract")
        if contract and not (CONTRACTS_DIR / contract).is_file():
            errors.append(
                f"{agent_dir.name}: handoff.contract not found in /contracts/v1 -> {contract}"
            )

    return manifest, errors


def _all_agents() -> list[Path]:
    return sorted(
        d for d in AGENTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def _resolve_model_deployment(env_name: str) -> str | None:
    return os.environ.get(env_name) or None


def _plan_actions(
    manifests: dict[str, dict[str, Any]],
    bindings: dict[str, AgentBinding],
    project_endpoint_hash: str,
    rebind: bool,
) -> list[PlannedAction]:
    plans: list[PlannedAction] = []
    for role, manifest in manifests.items():
        foundry = manifest.get("foundry") or {}
        agent_name = foundry.get("foundry_agent_name", "")
        env_name = foundry.get("model_deployment_env", "")
        model = _resolve_model_deployment(env_name) or "<UNSET>"
        assets = load_agent_assets(_role_to_agent_dir(role, manifests))
        instructions = compose_instructions(assets.agent_md_body)
        ihash = instructions_hash(instructions)

        existing = bindings.get(role)
        if existing is None:
            plans.append(
                PlannedAction(
                    role=role,
                    action="create",
                    agent_name=agent_name,
                    model_deployment_env=env_name,
                    instructions_hash=ihash,
                    reason="No binding present.",
                )
            )
            continue

        if (
            existing.project_endpoint_hash
            and existing.project_endpoint_hash != project_endpoint_hash
            and not rebind
        ):
            plans.append(
                PlannedAction(
                    role=role,
                    action="blocked",
                    agent_name=agent_name,
                    model_deployment_env=env_name,
                    instructions_hash=ihash,
                    reason=(
                        "project_endpoint_hash mismatch. Bindings belong to a different "
                        "Foundry project. Re-run with --rebind if this is intentional."
                    ),
                )
            )
            continue

        needs_update = (
            existing.instructions_hash != ihash
            or existing.model != model
            or existing.agent_name != agent_name
            or existing.manifest_version != str(manifest.get("version", ""))
        )
        if needs_update:
            plans.append(
                PlannedAction(
                    role=role,
                    action="update",
                    agent_name=agent_name,
                    model_deployment_env=env_name,
                    instructions_hash=ihash,
                    reason="instructions, model, or manifest version drifted.",
                )
            )
        else:
            plans.append(
                PlannedAction(
                    role=role,
                    action="skip",
                    agent_name=agent_name,
                    model_deployment_env=env_name,
                    instructions_hash=ihash,
                    reason="up-to-date",
                )
            )
    return plans


def _role_to_agent_dir(role: str, manifests: dict[str, dict[str, Any]]) -> str:
    """Recover the agent-dir name from the loaded manifest map."""
    # We track manifests by role (agent id from manifest.yaml). The dir
    # name is the /agents/<name>/ folder. We stored dirname alongside.
    return manifests[role]["__dir_name__"]  # type: ignore[no-any-return]


def _build_client(endpoint: str) -> FoundryAgentClientProtocol:
    from azure.identity import DefaultAzureCredential

    return FoundryAgentClient(endpoint=endpoint, credential=DefaultAzureCredential())


def _apply_plan(
    client: FoundryAgentClientProtocol,
    plans: list[PlannedAction],
    manifests: dict[str, dict[str, Any]],
    bindings: dict[str, AgentBinding],
    project_endpoint_hash: str,
) -> tuple[dict[str, AgentBinding], list[str]]:
    updated = dict(bindings)
    problems: list[str] = []
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for plan in plans:
        if plan.action == "skip":
            continue
        if plan.action == "blocked":
            problems.append(f"{plan.role}: {plan.reason}")
            continue
        manifest = manifests[plan.role]
        foundry = manifest.get("foundry") or {}
        env_name = foundry.get("model_deployment_env", "")
        model = _resolve_model_deployment(env_name)
        if not model:
            problems.append(
                f"{plan.role}: environment variable '{env_name}' is not set. "
                "Cannot create or update the remote agent."
            )
            continue
        assets = load_agent_assets(_role_to_agent_dir(plan.role, manifests))
        instructions = compose_instructions(assets.agent_md_body)
        temperature = foundry.get("temperature")
        response_format = foundry.get("response_format")
        try:
            if plan.action == "create":
                agent = client.create_agent(
                    name=plan.agent_name,
                    model=model,
                    instructions=instructions,
                    temperature=(float(temperature) if temperature is not None else None),
                    response_format=response_format,
                )
            else:  # update
                existing = updated[plan.role]
                agent = client.update_agent(
                    existing.assistant_id,
                    name=plan.agent_name,
                    model=model,
                    instructions=instructions,
                    temperature=(float(temperature) if temperature is not None else None),
                    response_format=response_format,
                )
        except FoundryProviderError as exc:
            problems.append(f"{plan.role}: {exc.safe_message}")
            continue
        except Exception as exc:  # noqa: BLE001 - surface classification failure safely
            problems.append(f"{plan.role}: unexpected provider error ({type(exc).__name__}).")
            continue
        updated[plan.role] = AgentBinding(
            role=plan.role,
            assistant_id=agent.id,
            agent_name=agent.name or plan.agent_name,
            model=agent.model or model,
            instructions_hash=instructions_hash(instructions),
            manifest_version=str(manifest.get("version", "")),
            response_format_mode=agent.response_format_mode,
            project_endpoint_hash=project_endpoint_hash,
            updated_at=now,
        )
        # Persist after each successful create/update so a partial
        # failure never leaves remote assistants stranded without a
        # local binding. save_bindings() is atomic (tmp + os.replace).
        save_bindings(updated)
    return updated, problems


def _load_all_manifests() -> tuple[dict[str, dict[str, Any]], list[str]]:
    manifests: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for agent_dir in _all_agents():
        manifest, errs = _validate_manifest(agent_dir)
        if errs:
            errors.extend(errs)
            continue
        role = str(manifest.get("id", ""))
        if not role:
            errors.append(f"{agent_dir.name}: manifest missing id")
            continue
        manifest["__dir_name__"] = agent_dir.name
        manifests[role] = manifest
    return manifests, errors


def _print_plan(plans: list[PlannedAction]) -> None:
    if not plans:
        print("No agents planned.")
        return
    for p in plans:
        marker = {
            "create": "[create]",
            "update": "[update]",
            "skip": "[skip]  ",
            "blocked": "[BLOCK] ",
        }.get(p.action, "[????]")
        print(
            f"  {marker} {p.role:35s} name={p.agent_name} "
            f"model_env={p.model_deployment_env}  ({p.reason})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Plan actions. No network.")
    mode.add_argument(
        "--apply", action="store_true", help="Create/update remote agents. Writes bindings."
    )
    mode.add_argument(
        "--check-connectivity",
        action="store_true",
        help="Instantiate the Foundry client and list agents to verify auth.",
    )
    parser.add_argument(
        "--rebind",
        action="store_true",
        help="Allow project_endpoint_hash change (moving between environments).",
    )
    args = parser.parse_args()

    if not AGENTS_DIR.is_dir():
        print(f"ERROR: /agents directory not found at {AGENTS_DIR}", file=sys.stderr)
        return 1

    manifests, errors = _load_all_manifests()
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        return 1

    endpoint = (
        os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
        or ""
    )

    if args.check_connectivity:
        if not endpoint:
            print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT not set. Cannot check connectivity.")
            return 2
        try:
            client = _build_client(endpoint)
            agents = client.list_agents()
            print(f"[ok] Foundry endpoint reachable. Existing agents: {len(agents)}.")
            return 0
        except FoundryProviderError as exc:
            print(f"[FAIL] {exc.safe_message}")
            return 2
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] Unexpected provider error ({type(exc).__name__}).")
            return 2

    endpoint_hash = hash_endpoint(endpoint) if endpoint else ""
    bindings = load_bindings()

    plans = _plan_actions(manifests, bindings, endpoint_hash, rebind=args.rebind)
    print(f"Planned actions for {len(plans)} agent(s):")
    _print_plan(plans)

    if args.dry_run:
        blocked = [p for p in plans if p.action == "blocked"]
        return 1 if blocked else 0

    # --apply
    if not endpoint:
        print(
            "ERROR: AZURE_AI_FOUNDRY_PROJECT_ENDPOINT not set. "
            "Populate services/api/.env from Terraform outputs.",
            file=sys.stderr,
        )
        return 2
    try:
        client = _build_client(endpoint)
    except ConfigurationError as exc:
        print(f"[FAIL] {exc.safe_message}")
        return 2

    updated, problems = _apply_plan(client, plans, manifests, bindings, endpoint_hash)
    save_bindings(updated)
    print(f"\nWrote bindings to {bindings_path().relative_to(REPO_ROOT)}")
    example = example_path()
    if not example.exists():
        print(f"(Consider committing an example at {example.relative_to(REPO_ROOT)}.)")
    if problems:
        print("\nProblems:")
        for p in problems:
            print(f"  - {p}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
