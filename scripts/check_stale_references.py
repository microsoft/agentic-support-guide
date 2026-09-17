"""Fail when the docs describe something the repo no longer has.

Three of the four documentation defects found in review were the same shape:
a removal landed in the code and the prose kept describing the old behaviour.
Nothing caught them, because a stale sentence is still valid markdown and a
stale identifier is still a working link.

This checks two things:

1. No file mentions an identifier that was deliberately removed.
2. No file uses the scenario vocabulary of the domain this repo migrated away
   from.

Run it directly, or let CI run it:

    python scripts/check_stale_references.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".terraform",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "dist",
    "images",
}
SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".ps1",
    ".tf",
    ".svg",
    ".example",
    ".txt",
}

# Removed on purpose. A mention means something was not finished.
FORBIDDEN = {
    r"\bsanitize_free_text\b": "sanitization was removed; use prompt_blocks",
    r"\bTelemetryRecorder\b": "replaced by Agent Framework instrumentation",
    r"\bapp/telemetry\.py\b": "replaced by app/observability.py",
    r"\b_protocol_validate\b": "never existed; use StepRunner.check_protocol",
    r"\bverify_deployment\.py\b": "deleted; smoke_test.py is the live check",
    r"workshop/basics": "dissolved into numbered modules",
    r"\bcanonical\(": "obfuscation folding was removed from determinations",
    # Education-domain vocabulary from the pre-migration scenario.
    r"\bdyslexia\b": "education-domain leftover",
    r"\bIEP\b": "education-domain leftover",
    r"Early Literacy": "education-domain leftover",
    r"Tier [23]\)": "education-domain leftover",
    r"letter-sound": "education-domain leftover; shipped twice in test payloads",
    r"\bphonem": "education-domain leftover",
    r"\bfluency\b": "education-domain leftover; dealerships measure time, not fluency",
    r"\bproficienc": "education-domain leftover; the KPI is 'Avg Process Score'",
    r"\bbehind pace\b": "education-domain leftover",
    r"\bdistrict_id\b": "renamed to dealer_group_id",
    r"\bdistrict_isolation_enabled\b": "renamed to dealer_group_isolation_enabled",
    r"\bdistricts?\b": "education-domain leftover; the scenario uses dealer groups",
    r"\bPlaceholderPage\b": "deleted; unbuilt routes were removed",
    r"\bsanitized_concern_text\b": "renamed to concern_text",
    # The declarative extra pulls powerfx -> pythonnet -> a .NET runtime.
    # This workshop is Python only; sample 4 was removed rather than ship it.
    r"agent-framework-declarative": "removed; it requires a .NET runtime",
    r"agent_framework\.declarative": "removed; it requires a .NET runtime",
    r"04_declarative_agent": "sample removed; samples renumbered 1-7",
    # "SMART goal" is education-sector jargon; the wire contract says goal.
    r"smart_goal": "renamed to goal_*; no SMART vocabulary in a public repo",
    r"SmartGoal": "renamed to GoalOption",
    r"\bSMART\b": "education-sector jargon; use plain 'goal'",
    r"\bSG-": "goal ids are GOAL-<category>-<n>",
}

# Prose-only rules. These name real code that exists under a different name
# elsewhere, so they would false-positive against the source files themselves.
FORBIDDEN_IN_DOCS = {
    r"\b_check_handoff\b": "renamed to PlanRun.check_handoff in executors.py",
    r"\bself\._evidence\b": "the executor attribute is self._retriever",
}

# This file necessarily names the things it forbids. `scanner.py` lists
# organization-suffix patterns it detects, one of which is "School District".
EXEMPT = {
    Path("scripts/check_stale_references.py"),
    Path("services/api/tests/scanner.py"),
}


def _source_files() -> list[Path]:
    found: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.relative_to(REPO_ROOT) in EXEMPT:
            continue
        found.append(path)
    return sorted(found)


def main() -> int:
    problems: list[str] = []
    files = _source_files()

    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        rules = dict(FORBIDDEN)
        if path.suffix == ".md":
            rules.update(FORBIDDEN_IN_DOCS)
        for pattern, reason in rules.items():
            for match in re.finditer(pattern, text, re.IGNORECASE):
                line = text[: match.start()].count("\n") + 1
                problems.append(f"{rel}:{line}: '{match.group(0)}' - {reason}")

    print(f"Scanned {len(files)} file(s) for removed identifiers.")
    if problems:
        print(f"\n{len(problems)} stale reference(s):\n")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("No stale references.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
