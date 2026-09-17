"""Shared setup for the workshop samples.

Every sample needs the same two settings and the same chat client, so that
lives here rather than being re-typed eight times.

The names are read in two forms. `FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_MODEL`
are what the Agent Framework docs use, so a sample copied out of this repo
matches what you read there. `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` /
`FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER` are what Module 0's `populate-env.ps1`
writes, so if you have already done Module 0 the samples just work.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# (docs name, this repo's name)
ENDPOINT_VARS = ("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
MODEL_VARS = ("FOUNDRY_MODEL", "FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER")

ENV_FILE = Path(__file__).resolve().parents[2] / "services" / "api" / ".env"


def _load_env_file() -> None:
    """Read services/api/.env if Module 0 created it. Never overrides a real env var."""

    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def setting(names: tuple[str, ...], example: str) -> str:
    """First of `names` that is set, or a message naming both and exiting."""

    _load_env_file()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    docs_name, repo_name = names
    print(
        f"Set {docs_name} (or run Module 0, which writes {repo_name}).\n\n"
        f'  $env:{docs_name} = "{example}"\n'
        "  az login\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


@asynccontextmanager
async def chat_client() -> AsyncIterator[Any]:
    """A FoundryChatClient authenticated with your `az login` session.

    `async with` because neither the client nor the credential closes itself:
    `Agent.__aexit__` does not close a client it did not open, so a script
    that just calls this would leak an HTTP session per run.

    `AzureCliCredential` rather than `DefaultAzureCredential` so a sample
    fails immediately with "run az login" instead of spending 30 seconds
    probing credential sources that are not configured on a laptop. The
    deployed app uses `DefaultAzureCredential`, because there the
    identity is a managed identity rather than your CLI session.
    """

    from agent_framework.foundry import FoundryChatClient
    from azure.identity.aio import AzureCliCredential

    credential = AzureCliCredential()
    client = FoundryChatClient(
        project_endpoint=setting(
            ENDPOINT_VARS,
            "https://<your-project>.services.ai.azure.com/api/projects/<name>",
        ),
        model=setting(MODEL_VARS, "gpt-4.1-mini"),
        credential=credential,
    )
    try:
        yield client
    finally:
        # Independent, so one failing close cannot strand the others.
        for closable in (
            getattr(client, "client", None),
            getattr(client, "project_client", None),
            credential,
        ):
            close = getattr(closable, "close", None)
            if close is None:
                continue
            try:
                await close()
            except Exception as exc:  # noqa: BLE001 - teardown is best effort
                print(f"warning: closing {type(closable).__name__} failed: {exc}", file=sys.stderr)


def banner(title: str) -> None:
    print(f"\n=== {title} ===")
