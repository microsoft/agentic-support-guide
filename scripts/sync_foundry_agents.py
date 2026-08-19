#!/usr/bin/env python
"""Validate /agents manifests and (optionally) test Azure AI Foundry connectivity.

This script is intentionally a **dry-run and validation tool only**. It
does not create, update, or delete hosted-agent definitions because the
pinned openai + azure-identity SDK versions in this repo do not yet
expose a stable Foundry hosted-agent CRUD surface.

Usage:
    python scripts/sync_foundry_agents.py --dry-run
    python scripts/sync_foundry_agents.py --dry-run --check-connectivity

Rules:
- Never shells out to `az`. Uses `DefaultAzureCredential` for the
  optional connectivity check.
- Never prints secrets, endpoints, tokens, or resource IDs.
- Reads only /agents/*/manifest.yaml and agent.md and /contracts/v1/.
- Exit codes:
    0 - all manifests valid; sync path is pending stable SDK support.
    1 - one or more manifests failed validation.
    2 - connectivity check failed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
CONTRACTS_DIR = REPO_ROOT / "contracts" / "v1"

REQUIRED_MANIFEST_KEYS = ("id", "name", "version", "runtime", "contracts", "handoff", "safety")
REQUIRED_RUNTIME_KEYS = (
    "provider",
    "deployment_env",
    "api_version_env",
    "response_format",
    "max_output_tokens",
    "timeout_seconds",
)
REQUIRED_CONTRACT_SIDES = ("input", "output")
REQUIRED_CONTRACT_KEYS = ("schema_ref", "schema_version")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: PyYAML is required. `pip install pyyaml`.", file=sys.stderr)
        raise SystemExit(1) from None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _validate_manifest(agent_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = agent_dir / "manifest.yaml"
    agent_md = agent_dir / "agent.md"

    if not manifest_path.is_file():
        errors.append(f"{agent_dir.name}: missing manifest.yaml")
        return errors
    if not agent_md.is_file():
        errors.append(f"{agent_dir.name}: missing agent.md")

    manifest = _load_yaml(manifest_path)
    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            errors.append(f"{agent_dir.name}: manifest missing required key '{key}'")

    runtime = manifest.get("runtime") or {}
    for key in REQUIRED_RUNTIME_KEYS:
        if key not in runtime:
            errors.append(f"{agent_dir.name}: runtime.{key} missing")

    contracts = manifest.get("contracts") or {}
    for side in REQUIRED_CONTRACT_SIDES:
        block = contracts.get(side) or {}
        for key in REQUIRED_CONTRACT_KEYS:
            if key not in block:
                errors.append(f"{agent_dir.name}: contracts.{side}.{key} missing")

    # Referenced /contracts/v1 schema files exist.
    for side in ("input", "output"):
        block = contracts.get(side) or {}
        ref = block.get("schema_ref")
        if ref:
            local = CONTRACTS_DIR / ref
            if not local.is_file():
                errors.append(
                    f"{agent_dir.name}: contracts.{side}.schema_ref not found "
                    f"in /contracts/v1 -> {ref}"
                )

    # Referenced /contracts/v1 file exists for each handoff.
    for handoff in manifest.get("handoff") or []:
        contract = handoff.get("contract")
        if contract:
            expected = CONTRACTS_DIR / contract
            if not expected.is_file():
                errors.append(
                    f"{agent_dir.name}: handoff.contract not found in /contracts/v1 -> {contract}"
                )

    # Local schemas/*.json should also exist for local runtime type stubs.
    schemas_dir = agent_dir / "schemas"
    for expected_name in ("input.schema.json", "output.schema.json"):
        if not (schemas_dir / expected_name).is_file():
            errors.append(f"{agent_dir.name}: schemas/{expected_name} missing")

    return errors


def _check_connectivity() -> bool:
    """Optional: verify DefaultAzureCredential can obtain a token.

    Never prints the token. Does not call any Foundry endpoint. This
    only proves that `az login` has been performed and that the
    subscription context is reachable.
    """

    endpoint = os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
    if not endpoint:
        print(
            "AZURE_AI_FOUNDRY_ENDPOINT not set. "
            "Skipping connectivity check (populate .env and retry).",
            file=sys.stderr,
        )
        return False
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        print(
            "azure-identity not installed. Skipping connectivity check.",
            file=sys.stderr,
        )
        return False
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        return bool(token and token.token)
    except Exception:  # noqa: BLE001 - broad on purpose; we only care about success/failure
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate manifests only.")
    parser.add_argument(
        "--check-connectivity",
        action="store_true",
        help="Also verify DefaultAzureCredential can acquire a Cognitive Services token.",
    )
    args = parser.parse_args()

    if not args.dry_run:
        print(
            "Refusing to run without --dry-run. "
            "Hosted agent sync is pending stable SDK support."
        )
        return 1

    if not AGENTS_DIR.is_dir():
        print(f"ERROR: /agents directory not found at {AGENTS_DIR}", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("."):
            continue
        errors = _validate_manifest(agent_dir)
        if errors:
            all_errors.extend(errors)
            print(f"[FAIL] {agent_dir.name}")
            for e in errors:
                print(f"   - {e}")
        else:
            print(f"[ok]   {agent_dir.name} manifest + schemas valid")

    if all_errors:
        print(f"\n{len(all_errors)} validation error(s).")
        return 1

    print("\nAll agent manifests validated.")
    print("Hosted agent sync is pending stable SDK support - not performing CRUD.")

    if args.check_connectivity:
        print("\nRunning DefaultAzureCredential connectivity check...")
        if _check_connectivity():
            print("[ok] Cognitive Services token acquired via DefaultAzureCredential.")
            return 0
        print("[FAIL] Connectivity check failed. Run 'az login' and retry.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
