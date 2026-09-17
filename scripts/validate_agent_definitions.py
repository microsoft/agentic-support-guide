"""Validate the agent definitions in /agents. No network, no deployment.

GenAIOps boundary: agent behavior is defined by `/agents/<id>/agent.md` and
`manifest.yaml`, versioned in git and loaded by the app at runtime. There is
nothing to deploy - the runtime builds ephemeral agents per call - so this
script only checks that the definitions are well formed and consistent with
the contracts in `/contracts/v1`.

Infrastructure (DevOps) is provisioned separately by Terraform in `/infra`
and never creates agents.

Usage:
  python scripts/validate_agent_definitions.py            # offline validation
  python scripts/validate_agent_definitions.py --check-connectivity
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.foundry_agents import (
    compose_instructions,
    declared_response_format,
    instructions_hash,
    load_agent_assets,
)

AGENTS_DIR = REPO_ROOT / "agents"
CONTRACTS_DIR = REPO_ROOT / "contracts" / "v1"
ENV_FILE = REPO_ROOT / "services" / "api" / ".env"

REQUIRED_MANIFEST_KEYS = (
    "id",
    "name",
    "version",
    "runtime",
    "contracts",
    "handoff",
    "safety",
)
REQUIRED_FOUNDRY_KEYS = ("model_deployment_env", "response_format")
REQUIRED_CONTRACT_SIDES = ("input", "output")
REQUIRED_CONTRACT_KEYS = ("schema_ref", "schema_version")


def _load_env_file() -> None:
    """Read services/api/.env; real environment variables win."""

    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _all_agents() -> list[Path]:
    return sorted(d for d in AGENTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))


def _validate_manifest(agent_dir: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    manifest_path = agent_dir / "manifest.yaml"
    if not manifest_path.is_file():
        return {}, [f"{agent_dir.name}: manifest.yaml not found"]

    manifest: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    foundry = manifest.get("foundry") or {}
    is_text_agent = foundry.get("response_format") == "text"

    for key in REQUIRED_MANIFEST_KEYS:
        if key == "contracts" and is_text_agent:
            continue
        if key not in manifest:
            errors.append(f"{agent_dir.name}: manifest missing '{key}'")

    for key in REQUIRED_FOUNDRY_KEYS:
        if not foundry.get(key):
            errors.append(f"{agent_dir.name}: manifest.foundry missing '{key}'")

    # Persisted-agent leftovers must not come back.
    if "foundry_agent_name" in foundry:
        errors.append(
            f"{agent_dir.name}: manifest.foundry.foundry_agent_name names a persisted "
            "agent; agents are ephemeral and this key must be removed"
        )

    contracts = manifest.get("contracts") or {}
    # A text agent answers in prose, so there is no schema for it to honour.
    # Requiring one produced a manifest that borrowed the data analyst's.
    if foundry.get("response_format") == "text":
        if contracts:
            errors.append(
                f"{agent_dir.name}: response_format is text, so contracts must be omitted"
            )
    else:
        for side in REQUIRED_CONTRACT_SIDES:
            block = contracts.get(side) or {}
            for key in REQUIRED_CONTRACT_KEYS:
                if not block.get(key):
                    errors.append(f"{agent_dir.name}: contracts.{side} missing '{key}'")
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


def _validate_instructions(agent_dir: Path) -> tuple[str, list[str]]:
    """Compose instructions the way the runtime does and sanity-check them."""

    errors: list[str] = []
    assets = load_agent_assets(agent_dir.name)
    instructions = compose_instructions(
        assets.agent_md_body,
        frontmatter=assets.agent_md_frontmatter,
        response_format=declared_response_format(assets.manifest),
    )
    if not assets.agent_md_body.strip():
        errors.append(f"{agent_dir.name}: agent.md body is empty")
    # The behavioural rules live in frontmatter; dropping them silently
    # produces plausible but off-contract model output.
    for key in ("constraints", "safety_rules"):
        if not assets.agent_md_frontmatter.get(key):
            errors.append(f"{agent_dir.name}: agent.md frontmatter missing '{key}'")
    return instructions, errors


def _show_instructions(name: str) -> int:
    names = [d.name for d in _all_agents()]
    if name not in names:
        print(
            f"ERROR: unknown agent '{name}'. Choose one of: {', '.join(names)}",
            file=sys.stderr,
        )
        return 1
    instructions, _ = _validate_instructions(AGENTS_DIR / name)
    print(instructions)
    return 0


def _validate_all() -> list[str]:
    """Validate every agent, printing one line each. Returns all errors."""

    all_errors: list[str] = []
    print(f"Validating {len(_all_agents())} agent definition(s):")
    for agent_dir in _all_agents():
        manifest, errors = _validate_manifest(agent_dir)
        instructions, more = _validate_instructions(agent_dir)
        errors.extend(more)
        all_errors.extend(errors)
        if errors:
            for err in errors:
                print(f"  [FAIL] {err}")
            continue
        foundry = manifest.get("foundry") or {}
        env_name = str(foundry.get("model_deployment_env", ""))
        state = os.environ.get(env_name) or "<unset>"
        print(
            f"  [ok]   {agent_dir.name:22s} model_env={env_name} ({state}) "
            f"instructions_hash={instructions_hash(instructions)[:12]}"
        )
    return all_errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-connectivity",
        action="store_true",
        help="Live check: verify the Foundry project endpoint and credential work.",
    )
    parser.add_argument(
        "--show-instructions",
        metavar="AGENT",
        help="Print the composed instructions for one agent, for pasting into the portal.",
    )
    args = parser.parse_args()

    _load_env_file()

    if not AGENTS_DIR.is_dir():
        print(f"ERROR: /agents directory not found at {AGENTS_DIR}", file=sys.stderr)
        return 1

    if args.show_instructions:
        return _show_instructions(args.show_instructions)

    all_errors = _validate_all()
    if all_errors:
        print(f"\n{len(all_errors)} problem(s) found.", file=sys.stderr)
        return 1

    if args.check_connectivity:
        return _check_connectivity()

    print(
        "\nAll agent definitions are valid. Publish them to Foundry with:\n"
        "  .\\services\\api\\.venv\\Scripts\\python.exe "
        "scripts\\publish_prompt_agents.py --suffix <you> --apply"
    )
    return 0


def _check_connectivity() -> int:
    endpoint = (
        os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
        or ""
    )
    if not endpoint:
        print(
            "\nAZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. "
            "Run .\\scripts\\populate-env.ps1 first.",
            file=sys.stderr,
        )
        return 2
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
        list(client.deployments.list())
    except Exception as exc:  # noqa: BLE001 - surfaced as a learner-facing hint
        print(
            f"\n[fail] Could not reach the Foundry project: {type(exc).__name__}",
            file=sys.stderr,
        )
        print(
            "       Check: 'az login', the correct subscription, and that RBAC "
            "has propagated (can take a few minutes after terraform apply).",
            file=sys.stderr,
        )
        return 2
    print("\n[ok] Foundry project endpoint reachable with the current credential.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
