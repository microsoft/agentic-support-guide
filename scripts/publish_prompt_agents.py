"""Publish the three roles to Foundry as **prompt agents**.

GenAIOps step, deliberately separate from Terraform (DevOps). Terraform
provisions infrastructure; this publishes agent definitions. Neither one
does the other's job.

Why prompt agents: they are Foundry's current agent model, so they render
natively in the portal Agents list. The definition published here is
composed from the same `/agents/<id>/agent.md` the runtime uses, so what you
see in the portal is what the app runs.

Usage:
  python scripts/publish_prompt_agents.py            # dry run
  python scripts/publish_prompt_agents.py --apply    # publish a version
  python scripts/publish_prompt_agents.py --list     # what's in the project
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.foundry_agents.maf_client import aclose_foundry_client
from app.foundry_agents.maf_runtime import RoleDefinition
from app.foundry_agents.role_definitions import (
    ALL_AGENT_DIRS,
    ROLE_DIRS,
    WORKSHOP_AGENT_DIRS,
    load_agent_definitions,
)

ENV_FILE = REPO_ROOT / "services" / "api" / ".env"
AGENT_NAME_PREFIX = "asg-"
PUBLISH_ATTEMPTS = 3
PUBLISH_BACKOFF_SECONDS = 10


def _agent_name(role: str, suffix: str, variant: str = "") -> str:
    """Learner-suffixed so a whole workshop can share one Foundry project.

    `variant` gives Module 8 a second independently addressable agent alongside
    the base name. Publishing twice under the same name would only add versions,
    and the newest would win - there would be nothing to compare.
    """

    tail = f"-{variant}" if variant else ""
    return f"{AGENT_NAME_PREFIX}{role}-{suffix}{tail}"


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


async def _build_prompt_agent(endpoint: str, definition: RoleDefinition, agent_name: str) -> Any:
    """Turn a local agent.md definition into a publishable prompt agent."""

    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient, to_prompt_agent
    from azure.identity.aio import DefaultAzureCredential as AsyncCredential

    credential = AsyncCredential()
    client = None
    try:
        client = FoundryChatClient(
            project_endpoint=endpoint,
            model=definition.model_deployment,
            credential=credential,
        )
        # `is not None`, not truthiness: temperature 0 is a deliberate setting
        # and the falsy check silently dropped it.
        options = (
            {"temperature": definition.temperature} if definition.temperature is not None else {}
        )
        async with Agent(
            client=client,
            name=agent_name,
            instructions=definition.instructions,
            default_options=options or None,
        ) as agent:
            return to_prompt_agent(agent)
    finally:
        # Exiting the Agent context does NOT close FoundryChatClient's own
        # HTTP sessions, so this has to be explicit or the script leaks a
        # socket per role published.
        if client is not None:
            await aclose_foundry_client(client)
        await _aclose(credential)


@contextmanager
def _project_client(endpoint: str) -> Iterator[Any]:
    """An AIProjectClient that closes its own credential.

    Neither the client nor the credential releases its HTTP session on
    garbage collection, so every entry point that builds one has to close it.
    """

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)
    try:
        yield client
    finally:
        client.close()
        credential.close()


async def _create_version(endpoint: str, agent_name: str, prompt_agent: Any) -> str:
    """create_version, retried.

    It intermittently exceeds its read timeout on a freshly provisioned
    project. Retrying is safe: a repeat call just adds another version.
    """

    last_exc: Exception | None = None
    with _project_client(endpoint) as project:
        for attempt in range(1, PUBLISH_ATTEMPTS + 1):
            try:
                version = project.agents.create_version(
                    agent_name=agent_name, definition=prompt_agent
                )
            except Exception as exc:  # noqa: BLE001 - retried, then reported
                last_exc = exc
                if attempt == PUBLISH_ATTEMPTS:
                    break
                delay = PUBLISH_BACKOFF_SECONDS * attempt
                print(
                    f"  [retry {attempt}/{PUBLISH_ATTEMPTS - 1}] {agent_name}: "
                    f"{type(exc).__name__}; retrying in {delay}s",
                    file=sys.stderr,
                )
                await asyncio.sleep(delay)
                continue
            return f"published {agent_name} version={getattr(version, 'version', '?')}"

    raise RuntimeError(
        f"{agent_name} failed after {PUBLISH_ATTEMPTS} attempts: "
        f"{type(last_exc).__name__}: {last_exc}"
    )


async def _publish_role(
    endpoint: str,
    definition: RoleDefinition,
    *,
    suffix: str,
    apply: bool,
    variant: str = "",
) -> str:
    agent_name = _agent_name(definition.role, suffix, variant)
    prompt_agent = await _build_prompt_agent(endpoint, definition, agent_name)
    if not apply:
        return f"[dry-run] would publish {agent_name} (model={definition.model_deployment})"
    return await _create_version(endpoint, agent_name, prompt_agent)


async def _aclose(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is None:
        return
    result = close()
    if asyncio.iscoroutine(result):
        await result


def _delete_agents(endpoint: str, suffix: str, variants: tuple[str, ...] = ()) -> int:
    """Delete only this learner's agents, never anyone else's.

    Names are `<prefix><role>-<suffix>[-<variant>]`, all single-dash, so
    `asg-explainer-ann-smith` is genuinely ambiguous: it could be suffix
    `ann` + variant `smith`, or suffix `ann-smith` with no variant. No prefix
    match can resolve that, and the previous `startswith(base + "-")` meant
    learner `ann` deleted learner `ann-smith`'s agents.

    So: delete exact names only. Variants must be named explicitly with
    `--variant`, which is how they were created in the first place.
    """

    if variants:
        # Scoped to the named variant only. Seeding the base names here too
        # would make `--variant strict --delete` wipe every agent for the
        # suffix, which is the opposite of naming one explicitly.
        targets: set[str] = set()
        for variant in variants:
            targets |= {_agent_name(role, suffix, variant) for role in ALL_AGENT_DIRS.values()}
    else:
        targets = {_agent_name(role, suffix) for role in ALL_AGENT_DIRS.values()}

    with _project_client(endpoint) as project:
        present = {str(getattr(a, "name", "") or "") for a in project.agents.list()}
        mine = sorted(present & targets)
        if not mine:
            print(f"No agents found for suffix {suffix!r}. Nothing to delete.")
            skipped = sorted(n for n in present if n.startswith(f"{AGENT_NAME_PREFIX}"))
            if skipped:
                print("Present but not deleted (not an exact match for this suffix):")
                for name in skipped:
                    print(f"  {name}")
                print("Pass --variant <name> to delete a variant.")
            return 0
        for name in mine:
            project.agents.delete(name)
            print(f"deleted {name}")
    return 0


def _list_agents(endpoint: str) -> int:
    with _project_client(endpoint) as project:
        found = list(project.agents.list())
    if not found:
        print("No agents in this Foundry project.")
        return 0
    print(f"{len(found)} agent(s) in the project:")
    for agent in found:
        print(f"  {getattr(agent, 'name', '?')}")
    return 0


async def _publish_all(
    endpoint: str,
    *,
    apply: bool,
    suffix: str,
    dirs: dict[str, str],
    variant: str = "",
) -> int:
    roles = load_agent_definitions(dirs)
    if not roles:
        print(
            "No role definitions resolved. Check that the "
            "FOUNDRY_MODEL_DEPLOYMENT_* variables are set.",
            file=sys.stderr,
        )
        return 2

    print(f"Publishing {len(roles)} prompt agent(s) from /agents definitions:")
    failed: list[str] = []
    for definition in roles.values():
        try:
            print(
                "  "
                + await _publish_role(
                    endpoint,
                    definition,
                    suffix=suffix,
                    apply=apply,
                    variant=variant,
                )
            )
        except Exception as exc:  # noqa: BLE001 - learner-facing summary
            # Keep going: one flaky agent should not block the rest, and
            # re-running only adds a version to whatever already succeeded.
            print(
                f"  [fail] {definition.role}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            failed.append(definition.role)

    if failed:
        print(
            f"\n{len(failed)} agent(s) failed: {', '.join(failed)}.\n"
            "Re-run the same command; publishing is safe to repeat.",
            file=sys.stderr,
        )
        return 1

    if apply:
        print("\nDone. These appear in the Foundry portal under Agents.")
    else:
        print("\nDry run. Re-run with --apply to publish.")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Publish a new version of each agent.")
    parser.add_argument("--list", action="store_true", help="List agents in the project and exit.")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete this learner's agents. Requires --suffix.",
    )
    parser.add_argument(
        "--suffix",
        default=os.environ.get("WORKSHOP_LEARNER_SUFFIX", ""),
        help=(
            "Learner suffix appended to every agent name, so learners sharing a "
            "project never collide. Defaults to WORKSHOP_LEARNER_SUFFIX."
        ),
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--workshop-only",
        action="store_true",
        help="Publish only the standalone workshop agents, not the coordinator roles.",
    )
    scope.add_argument(
        "--roles-only",
        action="store_true",
        help="Publish only the coordinator roles, leaving the explainer untouched.",
    )
    parser.add_argument(
        "--variant",
        default="",
        help=(
            "Extra name segment, e.g. --variant baseline. Publishes the same "
            "definition under a second name, for the Module 8 comparison."
        ),
    )
    return parser.parse_args()


def _require_endpoint() -> str | None:
    endpoint = _endpoint()
    if not endpoint:
        print(
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. Run .\\scripts\\populate-env.ps1 first.",
            file=sys.stderr,
        )
        return None
    return endpoint


def _selected_dirs(args: argparse.Namespace) -> dict[str, str]:
    if args.workshop_only:
        return WORKSHOP_AGENT_DIRS
    if args.roles_only:
        return ROLE_DIRS
    return ALL_AGENT_DIRS


def main() -> int:
    # Must precede argparse: the --suffix default reads the environment.
    _load_env()
    args = _parse_args()

    if args.list:
        endpoint = _require_endpoint()
        return _list_agents(endpoint) if endpoint else 2

    # Argument validation first: a bad --suffix is the caller's to fix, and
    # reporting a missing endpoint instead would send them down the wrong path.
    suffix = args.suffix.strip().lower()
    if not suffix:
        print(
            "A learner suffix is required so agents do not collide in a shared "
            "Foundry project. Pass --suffix <you> or set WORKSHOP_LEARNER_SUFFIX.",
            file=sys.stderr,
        )
        return 2
    if not re.fullmatch(r"[a-z0-9-]{1,24}", suffix):
        print(
            f"Invalid suffix {suffix!r}. Use 1-24 chars of a-z, 0-9 or '-'.",
            file=sys.stderr,
        )
        return 2

    variant = args.variant.strip().lower()
    if variant and not re.fullmatch(r"[a-z0-9-]{1,16}", variant):
        print(f"Invalid variant {variant!r}. Use 1-16 chars of a-z, 0-9 or '-'.", file=sys.stderr)
        return 2

    endpoint = _require_endpoint()
    if endpoint is None:
        return 2

    if args.delete:
        return _delete_agents(endpoint, suffix, (variant,) if variant else ())

    return asyncio.run(
        _publish_all(
            endpoint,
            apply=args.apply,
            suffix=suffix,
            dirs=_selected_dirs(args),
            variant=variant,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
