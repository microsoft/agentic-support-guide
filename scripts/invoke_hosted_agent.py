"""Invoke a deployed hosted agent over the Responses protocol.

Module 5 uses this to prove the hosted agent works, and to compare it
against the Module 1 prompt agent. Auth is Entra: the managed endpoint
accepts a token for the Foundry scope, so no key is involved.

Usage:
  python scripts/invoke_hosted_agent.py --suffix <you> --question "..."
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "services" / "api" / ".env"
AGENT_NAME_PREFIX = "asg-hosted-explainer-"

DEFAULT_QUESTION = (
    "What does the district say about supporting a learner whose "
    "letter-sound fluency is behind pace?"
)


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


def main() -> int:
    # Must precede argparse: the --suffix default reads the environment, so
    # loading .env afterwards would ignore a suffix set only in that file.
    _load_env()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suffix",
        default=os.environ.get("WORKSHOP_LEARNER_SUFFIX", ""),
        help="Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
    )
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()

    suffix = args.suffix.strip().lower()
    if not suffix:
        print("Pass --suffix <you> or set WORKSHOP_LEARNER_SUFFIX.", file=sys.stderr)
        return 2

    project_endpoint = _endpoint()
    if not project_endpoint:
        print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        return 2

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    agent_name = f"{AGENT_NAME_PREFIX}{suffix}"
    project = AIProjectClient(endpoint=project_endpoint, credential=DefaultAzureCredential())
    # Binding agent_name here points the OpenAI client at the hosted agent's
    # managed endpoint. Auth is Entra; no key is involved.
    client = project.get_openai_client(agent_name=agent_name)

    print(f"Agent    : {agent_name}")
    try:
        details = project.agents.get(agent_name)
        identity = getattr(details, "instance_identity", None) or {}
        principal = (
            identity.get("principal_id")
            if isinstance(identity, dict)
            else getattr(identity, "principal_id", None)
        )
        # Module 5 step 6: this principal is the agent's own, not the caller's.
        print(f"Identity : {principal or '(none reported)'}")
    except Exception as exc:  # noqa: BLE001 - informational only
        print(f"Identity : unavailable ({type(exc).__name__})")
    print(f"Question : {args.question}\n")

    started = time.monotonic()
    try:
        response = client.responses.create(input=args.question, model=agent_name)
    except Exception as exc:  # noqa: BLE001 - learner-facing summary
        print(f"Failed after {time.monotonic() - started:.1f}s", file=sys.stderr)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(f"Answered in {elapsed:.1f}s\n")
    text = getattr(response, "output_text", "") or _extract_text(response)
    print(text or repr(response)[:1000])
    return 0


def _extract_text(response: object) -> str:
    """Fallback when the SDK does not expose output_text."""

    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


if __name__ == "__main__":
    raise SystemExit(main())
