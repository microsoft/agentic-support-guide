"""Module 9: grade the agents instead of guessing whether they are good.

`scripts/run_evals.py` answers "is the output structurally valid and safe?"
with deterministic checks. That is necessary but it cannot tell you whether
an answer is actually grounded in the evidence or actually addresses the
question. This script answers that, using Foundry's built-in graders via
Microsoft Agent Framework.

The judge is a separate model deployment from the agents' own model, so
grading load never starves the agents and learners can see that the grader
is a different model from the thing being graded.

Usage:
  python scripts/run_agent_evals.py --list-evaluators
  python scripts/run_agent_evals.py --dry-run
  python scripts/run_agent_evals.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

CASES_PATH = REPO_ROOT / "evals" / "synthetic_cases.jsonl"
ENV_FILE = REPO_ROOT / "services" / "api" / ".env"

# Graders that make sense for a grounded, single-turn advisory agent.
# Groundedness needs `context`; relevance and coherence do not.
DEFAULT_EVALUATORS = ("groundedness", "relevance", "coherence")

# A grade below this on a 1-5 scale is treated as a regression.
PASS_THRESHOLD = 3.0


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


def _load_cases() -> list[dict[str, Any]]:
    lines = CASES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


async def _build_context(case: dict[str, Any]) -> str:
    """Groundedness is scored against this text, so it must be the real evidence."""

    from app.evidence import EvidenceRequest, FixtureEvidenceRetriever

    bundle = await FixtureEvidenceRetriever().retrieve(
        EvidenceRequest(
            dealer_group_id=case["dealer_group_id"],
            category=case["category"],
            detected_need_hint="",
        )
    )
    return "\n".join(
        f"[{c.citation_id}] {c.source_title} ({c.section_or_page}): {c.evidence_summary}"
        for c in bundle.citations
    )


def _resolve_evaluators(names: tuple[str, ...]) -> list[str]:
    from agent_framework.foundry import FoundryEvals

    resolved: list[str] = []
    for name in names:
        constant = getattr(FoundryEvals, name.upper(), None)
        if constant is None:
            raise SystemExit(
                f"Unknown evaluator '{name}'. Run --list-evaluators to see valid names."
            )
        resolved.append(constant)
    return resolved


def _list_evaluators() -> int:
    from agent_framework.foundry import FoundryEvals

    names = sorted(n for n in dir(FoundryEvals) if n.isupper() and not n.startswith("_"))
    print(f"{len(names)} built-in Foundry evaluators:")
    for name in names:
        marker = "  <- default" if name.lower() in DEFAULT_EVALUATORS else ""
        print(f"  {name.lower()}{marker}")
    return 0


def _grounded_prompt(query: str, context: str) -> str:
    """The fenced block matches what the runtime envelope tells the agent to trust."""

    return f"<<<UNTRUSTED_DATA>>>\n{context}\n<<<END_UNTRUSTED_DATA>>>\n\n{query}"


async def _grade_all(
    endpoint: str,
    *,
    agent_model: str,
    judge_model: str,
    evaluator_names: tuple[str, ...],
    cases: list[dict[str, Any]],
    queries: list[str],
    contexts: list[str],
) -> int:
    """Returns the number of cases that regressed."""

    from agent_framework import Agent, Message, evaluate_agent
    from agent_framework.foundry import FoundryChatClient, FoundryEvals
    from app.foundry_agents.role_definitions import (
        WORKSHOP_AGENT_DIRS,
        load_agent_definitions,
    )
    from azure.identity.aio import DefaultAzureCredential

    definition = load_agent_definitions(WORKSHOP_AGENT_DIRS)["support-explainer-agent"]
    evaluators = _resolve_evaluators(evaluator_names)

    credential = DefaultAzureCredential()
    failures = 0
    client: Any = None
    try:
        client = FoundryChatClient(
            project_endpoint=endpoint, model=agent_model, credential=credential
        )
        grader = FoundryEvals(
            project_client=None,
            client=client,
            model=judge_model,
            evaluators=evaluators,
        )

        print()
        async with Agent(
            client=client,
            name="asg-eval-support-explainer",
            instructions=definition.instructions,
        ) as agent:
            for case, query, context in zip(cases, queries, contexts, strict=True):
                # evaluate_agent(queries=...) sends the bare query to the agent
                # and attaches `context` to the grading item only, so the agent
                # would answer blind and groundedness would score it against
                # evidence it never saw. Run it ourselves with the evidence,
                # then grade that response against the clean question.
                response = await agent.run([Message("user", [_grounded_prompt(query, context)])])
                results = await evaluate_agent(
                    agent=agent,
                    queries=query,
                    responses=response,
                    evaluators=grader,
                    context=context,
                    eval_name=f"asg-{case['id']}",
                )
                if _report(str(case["id"]), results):
                    failures += 1
    finally:
        # Exiting the Agent context leaves the chat client's inner sessions
        # open, so close them explicitly before the credential.
        for attr in ("client", "project_client"):
            await _aclose(getattr(client, attr, None))
        await _aclose(credential)
    return failures


async def _run(evaluator_names: tuple[str, ...], apply: bool) -> int:
    endpoint = _endpoint()
    if not endpoint:
        print(
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. Run .\\scripts\\populate-env.ps1 first.",
            file=sys.stderr,
        )
        return 2

    agent_model = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER", "")
    # Grading with the model under test is the cheap default, but a separate
    # judge deployment keeps the grader honest when one is configured.
    judge_model = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_JUDGE", "") or agent_model
    if not agent_model:
        print("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER is not set.", file=sys.stderr)
        return 2

    cases = _load_cases()
    queries = [str(c["concern_text"]) for c in cases]
    contexts = [await _build_context(c) for c in cases]

    print(f"Evaluating {len(cases)} case(s)")
    print(f"  agent model : {agent_model}")
    print(f"  judge model : {judge_model}")
    print(f"  evaluators  : {', '.join(evaluator_names)}")

    if not apply:
        print("\nDry run. Nothing was sent to Azure. Re-run with --apply to grade.")
        for case, context in zip(cases, contexts, strict=True):
            print(f"  {case['id']}: {len(context)} chars of grounding context")
        return 0

    failures = await _grade_all(
        endpoint,
        agent_model=agent_model,
        judge_model=judge_model,
        evaluator_names=evaluator_names,
        cases=cases,
        queries=queries,
        contexts=contexts,
    )
    print(f"\n{len(cases) - failures}/{len(cases)} case(s) passed the quality gate.")
    return 1 if failures else 0


def _collect_scores(runs: list[Any]) -> list[tuple[str, float, bool | None]]:
    """Flatten `EvalResults -> items -> scores` into (name, score, passed).

    Booleans are excluded because `isinstance(True, int)` is True and a
    pass/fail flag is not a score.
    """

    scores: list[tuple[str, float, bool | None]] = []
    for run in runs:
        for item in getattr(run, "items", None) or []:
            for score in getattr(item, "scores", None) or []:
                value = getattr(score, "score", None)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    scores.append(
                        (
                            str(getattr(score, "name", "") or "?"),
                            float(value),
                            getattr(score, "passed", None),
                        )
                    )
    return scores


def _report(case_id: str, results: Any) -> bool:
    """Print one line per case. Returns True if this case regressed.

    A run that produced no scores is a FAILURE, not a pass: it means the
    grader did not actually grade anything.
    """

    runs = results if isinstance(results, list) else [results]

    status_errors = [
        f"{getattr(r, 'status', '?')}: {getattr(r, 'error', '') or 'no detail'}"
        for r in runs
        if getattr(r, "status", "completed") != "completed"
    ]
    if status_errors:
        print(f"  [fail] {case_id}: grader did not complete - {'; '.join(status_errors)}")
        return True

    scores = _collect_scores(runs)
    if not scores:
        print(f"  [fail] {case_id}: grader returned no scores - nothing was graded")
        return True

    # The grader's own verdict wins where it has one: a rubric can reject a
    # response that still scores above our local threshold.
    below = [n for n, v, _ in scores if v < PASS_THRESHOLD]
    rejected = [n for n, _, p in scores if p is False]
    # A missing verdict is a failed verdict: defaulting to True would let an
    # SDK shape change silently turn a regression into a green run.
    all_passed = all(getattr(r, "all_passed", False) for r in runs)
    regressed = bool(below or rejected) or not all_passed

    detail = ", ".join(f"{n}={v:.2f}" for n, v, _ in sorted(scores))
    print(f"  [{'fail' if regressed else 'ok  '}] {case_id}  {detail}")
    if rejected:
        print(f"           grader rejected: {', '.join(sorted(set(rejected)))}")

    url = next(
        (getattr(r, "report_url", None) for r in runs if getattr(r, "report_url", None)),
        None,
    )
    if url:
        print(f"           report: {url}")
    return regressed


async def _aclose(obj: Any) -> None:
    close = getattr(obj, "close", None)
    if close is None:
        return
    result = close()
    if asyncio.iscoroutine(result):
        await result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Actually call Azure and grade.")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be graded, call nothing. Default.",
    )
    parser.add_argument(
        "--list-evaluators", action="store_true", help="List built-in graders and exit."
    )
    parser.add_argument(
        "--evaluators",
        default=",".join(DEFAULT_EVALUATORS),
        help=f"Comma-separated grader names. Default: {','.join(DEFAULT_EVALUATORS)}",
    )
    args = parser.parse_args()

    _load_env()
    if args.list_evaluators:
        return _list_evaluators()

    names = tuple(n.strip() for n in args.evaluators.split(",") if n.strip())
    return asyncio.run(_run(names, apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
