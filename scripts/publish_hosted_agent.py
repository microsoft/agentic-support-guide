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
    python scripts/publish_hosted_agent.py --suffix <your-alias>            # dry run
    python scripts/publish_hosted_agent.py --suffix <your-alias> --apply
    python scripts/publish_hosted_agent.py --suffix <your-alias> --status
    python scripts/publish_hosted_agent.py --suffix <your-alias> --delete
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

from app.foundry_agents import compose_instructions, declared_response_format, load_agent_assets

ENV_FILE = REPO_ROOT / "services" / "api" / ".env"
SOURCE_DIR = REPO_ROOT / "hosted" / "support-explainer"
# Shared with the API so the hosted agent cannot drift from the prompt blocks and
# determination policy the coordinator uses. Stdlib-only, so they bundle cleanly.
#
# This is a build-time snapshot, not a live dependency: a deployed agent keeps
# the policy it shipped with until it is published again. Tightening the policy
# therefore needs a re-publish, or the internet-facing copy stays on the old one.
SHARED_DIR = REPO_ROOT / "services" / "api" / "app" / "agents" / "shared"
SHARED_MODULES = ("prompt_blocks.py", "determinations.py")
AGENT_DIR = "support-explainer"
AGENT_NAME_PREFIX = "asg-hosted-explainer-"

# Fixed zip entry timestamp, so identical sources hash identically. 1980-01-01
# is the earliest the zip format can represent.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

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
        assets.agent_md_body,
        frontmatter=assets.agent_md_frontmatter,
        response_format=declared_response_format(assets.manifest),
    )

    buffer = io.BytesIO()
    names: list[str] = []

    def _add(name: str, body: str) -> None:
        # A bare writestr(name, ...) stamps the entry with time.localtime(), so
        # the same sources produce a different sha256 on every run. Module 5
        # has learners compare that hash across runs, so pin the timestamp.
        info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, body)
        names.append(name)

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SOURCE_DIR.glob("*")):
            if path.is_file() and path.name not in ("instructions.md", *SHARED_MODULES):
                _add(path.name, path.read_text(encoding="utf-8"))
        # Generated, not committed: the hosted agent and the prompt agent
        # must never drift from the same agent.md.
        _add("instructions.md", instructions)
        for module in SHARED_MODULES:
            _add(module, (SHARED_DIR / module).read_text(encoding="utf-8"))
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


def _version_sort_key(listed: object) -> tuple[int, str]:
    raw = str(getattr(listed, "version", "") or "")
    return (int(raw), raw) if raw.isdigit() else (-1, raw)


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
    # Sorted explicitly rather than trusting list order: this module exists to
    # teach that list_versions cannot be trusted about state, so do not trust
    # it about ordering either.
    versions.sort(key=_version_sort_key, reverse=True)
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


def _rollback(suffix: str, target: str) -> int:
    """Point 100% of traffic at a specific version instead of @latest."""

    endpoint = _endpoint()
    if not endpoint:
        print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        return 2
    from azure.ai.projects.models import (
        AgentEndpointConfig,
        FixedRatioVersionSelectionRule,
        VersionSelector,
    )

    project = _project(endpoint)
    agent_name = _agent_name(suffix)

    # Rolling back onto a version that never built is the one mistake this
    # command must not let you make quietly.
    state, detail = _version_state(project.agents.get_version(agent_name, target))
    if state not in {"succeeded", "running", "active", "ready"}:
        suffix_detail = f" - {detail}" if detail else ""
        print(
            f"v{target} is '{state}'{suffix_detail}; refusing to send traffic to it.",
            file=sys.stderr,
        )
        return 1

    project.agents.update_details(
        agent_name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version=target, traffic_percentage=100)
                ]
            )
        ),
    )
    print(f"{agent_name}: 100% of traffic now pinned to v{target}.")
    return 0


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
    # Playground or invocation sessions block deletion until they expire.
    project.agents.delete(agent_name, force=True)
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
        "--rollback",
        metavar="VERSION",
        help="Pin 100%% of traffic to this version instead of @latest.",
    )
    parser.add_argument(
        "--suffix",
        default=os.environ.get("WORKSHOP_LEARNER_SUFFIX", ""),
        help="Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
    )
    args = parser.parse_args()

    suffix = args.suffix.strip().lower()
    if not suffix:
        print(
            "A learner suffix is required. Pass --suffix <your-alias> or set "
            "WORKSHOP_LEARNER_SUFFIX.",
            file=sys.stderr,
        )
        return 2
    if not re.fullmatch(r"[a-z0-9-]{1,24}", suffix):
        print(f"Invalid suffix {suffix!r}. Use 1-24 chars of a-z, 0-9 or '-'.", file=sys.stderr)
        return 2

    if args.delete:
        return _delete(suffix)
    if args.rollback:
        return _rollback(suffix, args.rollback)
    if args.status:
        return _status(suffix)
    return _publish(suffix, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
