"""Deploy the Support Explainer to Foundry as a hosted agent.

The whole point of this script is that nothing is hidden. It prints the
zip contents, the definition it is sending, and then polls the build and
prints the real status and error, so a failed deploy is diagnosable rather
than mysterious.

Flow:
  1. Compose instructions from agents/support-explainer/agent.md
  2. Zip main.py + requirements.txt + instructions.md (flat, at zip root)
  3. SHA-256 the zip (Foundry uses it for integrity and dedup)
  4. create_version_from_code -> Foundry builds the image remotely
  5. Poll until the version is running or failed

Usage:
  python scripts/publish_hosted_agent.py --suffix <you>            # dry run
  python scripts/publish_hosted_agent.py --suffix <you> --apply
  python scripts/publish_hosted_agent.py --suffix <you> --status
  python scripts/publish_hosted_agent.py --suffix <you> --delete
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.foundry_agents import compose_instructions, load_agent_assets

ENV_FILE = REPO_ROOT / "services" / "api" / ".env"
SOURCE_DIR = REPO_ROOT / "hosted" / "support-explainer"
# Shared with the API so the hosted agent cannot drift from the sanitizer the
# coordinator uses. Stdlib-only, so it bundles cleanly.
SANITIZER_SRC = REPO_ROOT / "services" / "api" / "app" / "agents" / "shared" / "sanitization.py"
AGENT_DIR = "support-explainer"
AGENT_NAME_PREFIX = "asg-hosted-explainer-"

# Verified against azure-ai-projects 2.3.0. Changing these is what breaks
# a deploy most often, so they are named constants, not inline literals.
RUNTIME = "python_3_13"
ENTRY_POINT = ["python", "main.py"]
PROTOCOL = "responses"
PROTOCOL_VERSION = "1.0.0"
CPU = "1"
MEMORY = "2Gi"

POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 900


def _load_env() -> None:
    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _endpoint() -> str:
    return (
        os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
        or ""
    )


def _agent_name(suffix: str) -> str:
    return f"{AGENT_NAME_PREFIX}{suffix}"


def _build_zip() -> tuple[bytes, list[str]]:
    """Flat zip: Foundry runs `python main.py` from the archive root."""

    assets = load_agent_assets(AGENT_DIR)
    instructions = compose_instructions(
        assets.agent_md_body, frontmatter=assets.agent_md_frontmatter
    )

    buffer = io.BytesIO()
    names: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SOURCE_DIR.glob("*")):
            if path.is_file() and path.name not in ("instructions.md", "sanitization.py"):
                zf.writestr(path.name, path.read_text(encoding="utf-8"))
                names.append(path.name)
        # Generated, not committed: the hosted agent and the prompt agent
        # must never drift from the same agent.md.
        zf.writestr("instructions.md", instructions)
        names.append("instructions.md")
        zf.writestr("sanitization.py", SANITIZER_SRC.read_text(encoding="utf-8"))
        names.append("sanitization.py")
    return buffer.getvalue(), names


def _definition(model_deployment: str, endpoint: str) -> Any:
    from azure.ai.projects.models import (
        CodeConfiguration,
        HostedAgentDefinition,
        ProtocolVersionRecord,
    )

    return HostedAgentDefinition(
        cpu=CPU,
        memory=MEMORY,
        environment_variables={
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": endpoint,
            "FOUNDRY_MODEL_DEPLOYMENT": model_deployment,
        },
        code_configuration=CodeConfiguration(
            runtime=RUNTIME,
            entry_point=ENTRY_POINT,
            # Foundry pip-installs requirements.txt during the image build.
            dependency_resolution="remote_build",
        ),
        protocol_versions=[ProtocolVersionRecord(protocol=PROTOCOL, version=PROTOCOL_VERSION)],
    )


def _project(endpoint: str) -> Any:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    return AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())


def _version_state(version: Any) -> tuple[str, str]:
    """Return (state, detail).

    `status` is the build/version outcome and must win. List responses also
    carry a `state` field describing the *agent*, which stays "active" even
    when the version failed to build - reading that first reports a broken
    deploy as a good one.
    """

    for attr in ("status", "state", "provisioning_state"):
        value = getattr(version, attr, None)
        if value:
            state = str(getattr(value, "value", value))
            break
    else:
        state = "unknown"

    error = getattr(version, "error", None)
    detail = ""
    if error is not None:
        code = getattr(error, "code", None) or (
            error.get("code") if isinstance(error, dict) else "?"
        )
        message = getattr(error, "message", None) or (
            error.get("message") if isinstance(error, dict) else ""
        )
        detail = f"{code}: {message}"
    return state.lower(), detail


def _poll(project: Any, agent_name: str, version_id: str) -> int:
    started = time.monotonic()
    last = ""
    while time.monotonic() - started < POLL_TIMEOUT_SECONDS:
        version = project.agents.get_version(agent_name, version_id)
        state, detail = _version_state(version)
        elapsed = int(time.monotonic() - started)
        if state != last:
            print(f"  [{elapsed:4}s] {state}{(' - ' + detail) if detail else ''}")
            last = state
        if state in ("succeeded", "running", "active", "ready"):
            print(f"\nBuild finished in {elapsed}s. Agent is {state}.")
            return 0
        if state in ("failed", "canceled", "cancelled"):
            print(f"\nBuild {state} after {elapsed}s.", file=sys.stderr)
            if detail:
                print(f"  {detail}", file=sys.stderr)
            print(
                "  Inspect logs in the Foundry portal under Agents -> this agent.",
                file=sys.stderr,
            )
            return 1
        time.sleep(POLL_INTERVAL_SECONDS)

    print(f"\nStill building after {POLL_TIMEOUT_SECONDS}s. Re-check with --status.")
    return 1


def _publish(suffix: str, apply: bool) -> int:
    endpoint = _endpoint()
    if not endpoint:
        print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        return 2
    model = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER", "")
    if not model:
        print("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER is not set.", file=sys.stderr)
        return 2

    agent_name = _agent_name(suffix)
    payload, names = _build_zip()
    digest = hashlib.sha256(payload).hexdigest()

    print(f"Agent name : {agent_name}")
    print(f"Runtime    : {RUNTIME}")
    print(f"Entrypoint : {' '.join(ENTRY_POINT)}")
    print(f"Protocol   : {PROTOCOL} v{PROTOCOL_VERSION}")
    print(f"Resources  : cpu={CPU} memory={MEMORY}")
    print(f"Zip        : {len(payload):,} bytes, sha256={digest[:16]}...")
    for name in names:
        print(f"             {name}")

    if not apply:
        print("\nDry run. Nothing uploaded. Re-run with --apply to deploy.")
        return 0

    project = _project(endpoint)
    stream = io.BytesIO(payload)
    # The SDK requires a .zip filename on the stream.
    stream.name = "code.zip"

    print("\nUploading and starting remote build...")
    started = time.monotonic()
    version = project.agents.create_version_from_code(
        agent_name=agent_name,
        definition=_definition(model, endpoint),
        code=stream,
        code_zip_sha256=digest,
    )
    version_id = str(getattr(version, "version", "") or "")
    print(f"Upload took {int(time.monotonic() - started)}s. Version: {version_id}")
    if not version_id:
        print(
            "No version id returned by create_version_from_code; cannot poll.",
            file=sys.stderr,
        )
        return 1
    return _poll(project, agent_name, version_id)


def _status(suffix: str) -> int:
    endpoint = _endpoint()
    if not endpoint:
        print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        return 2
    project = _project(endpoint)
    agent_name = _agent_name(suffix)
    versions = list(project.agents.list_versions(agent_name=agent_name))
    if not versions:
        print(f"No versions for {agent_name}.", file=sys.stderr)
        return 1
    print(f"{len(versions)} version(s) of {agent_name}:")
    healthy = {"succeeded", "running", "active", "ready"}
    latest_state = ""
    for listed in versions:
        vid = str(getattr(listed, "version", "") or "?")
        # list_versions reports status="active" even for versions that failed
        # to build, and omits `error`. Only get_version tells the truth.
        detailed = project.agents.get_version(agent_name, vid)
        state, detail = _version_state(detailed)
        if not latest_state:
            latest_state = state
        print(f"  v{vid}: {state}{(' - ' + detail) if detail else ''}")
    # Exit on the newest version so CI reflects what traffic actually hits.
    return 0 if latest_state in healthy else 1


def _delete(suffix: str) -> int:
    endpoint = _endpoint()
    if not endpoint:
        print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        return 2
    project = _project(endpoint)
    agent_name = _agent_name(suffix)
    present = {str(getattr(a, "name", "") or "") for a in project.agents.list()}
    if agent_name not in present:
        print(f"{agent_name} not found. Nothing to delete.")
        return 0
    project.agents.delete(agent_name)
    print(f"deleted {agent_name}")
    return 0


def main() -> int:
    # Must precede argparse: the --suffix default reads the environment.
    _load_env()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload and build.")
    parser.add_argument("--status", action="store_true", help="Show version states.")
    parser.add_argument("--delete", action="store_true", help="Delete this agent.")
    parser.add_argument(
        "--suffix",
        default=os.environ.get("WORKSHOP_LEARNER_SUFFIX", ""),
        help="Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
    )
    args = parser.parse_args()

    suffix = args.suffix.strip().lower()
    if not suffix:
        print(
            "A learner suffix is required. Pass --suffix <you> or set WORKSHOP_LEARNER_SUFFIX.",
            file=sys.stderr,
        )
        return 2
    if not re.fullmatch(r"[a-z0-9-]{1,24}", suffix):
        print(f"Invalid suffix {suffix!r}. Use 1-24 chars of a-z, 0-9 or '-'.", file=sys.stderr)
        return 2

    if args.delete:
        return _delete(suffix)
    if args.status:
        return _status(suffix)
    return _publish(suffix, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
