"""Render the workshop sample workflows to Mermaid.

    python scripts/render_workflow_diagram.py            # print
    python scripts/render_workflow_diagram.py --write    # update the docs

Uses `WorkflowViz`, so the diagram is generated from the workflow that
actually runs rather than drawn by hand. `tests/test_sample_workflows.py`
fails if the committed diagram and the built workflow disagree.

https://learn.microsoft.com/agent-framework/workflows/visualization
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = str(REPO_ROOT / "workshop" / "code")
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

# (builder key, marker used in the markdown, file the diagram lives in)
DIAGRAMS = (
    ("05_first_workflow", "sample-05", REPO_ROOT / "workshop" / "module-3-workflows.md"),
    ("07_conditional_repair", "sample-07", REPO_ROOT / "workshop" / "module-3-workflows.md"),
    ("app", "app-workflow", REPO_ROOT / "docs" / "orchestration-patterns.md"),
)


def _app_workflow() -> Any:
    """The application's own graph, built exactly as a request builds it.

    The runtime and retriever are only touched when the workflow
    *runs*; building it just stores them on the nodes. So a diagram needs no
    Azure, and it is still the real topology -- the same `build_plan_workflow`
    the API calls, with the same nodes and the same edge conditions.
    """

    from app.contracts_registry import load_registry
    from app.evidence import FixtureEvidenceRetriever
    from app.workflows.graph import build_plan_workflow
    from app.workflows.results import CoordinatorRequest, RunState

    request = CoordinatorRequest(
        dealer_group_id="GROUP-A",
        dealership_label="",
        region_id="",
        segment="",
        process_score=0,
        appointment_attendance_rate=0.0,
        followup_index=0.0,
        engagement_index=0.0,
        area_series=None,
        operations_series=None,
        category="lead-response",
        concern_text="",
        allowed_resources=(),
        allowed_goal_ids=(),
        allowed_strategy_ids=(),
    )
    state = RunState(
        correlation_id="diagram",
        dealer_group_id="GROUP-A",
        provider_model="",
        deadline=0.0,
    )
    return build_plan_workflow(
        request=request,
        state=state,
        runtime=cast(Any, None),
        contracts=load_registry(),
        evidence_retriever=FixtureEvidenceRetriever(),
        provider_display="",
    ).workflow


def render(key: str) -> str:
    from agent_framework import WorkflowViz

    if key == "app":
        return WorkflowViz(_app_workflow()).to_mermaid().strip()

    # Scoped rather than inserted at import: leaving `workshop/code/` on sys.path
    # would shadow real imports for whatever runs this next.
    sys.path.insert(0, SAMPLES)
    try:
        module = importlib.import_module(key)
    finally:
        if SAMPLES in sys.path:
            sys.path.remove(SAMPLES)
    return WorkflowViz(module.build_workflow()).to_mermaid().strip()


def _block(marker: str, mermaid: str) -> str:
    return f"<!-- {marker}:start -->\n```mermaid\n{mermaid}\n```\n<!-- {marker}:end -->"


def _pattern(marker: str) -> re.Pattern[str]:
    return re.compile(
        rf"<!-- {re.escape(marker)}:start -->.*?<!-- {re.escape(marker)}:end -->",
        re.DOTALL,
    )


def save_app_svg(destination: Path) -> Path:
    """Write the app graph as SVG using Agent Framework's own renderer.

    `save_svg` shells out to Graphviz `dot`, which App Service does not have.
    The SVG is therefore generated here and committed, the same way
    docs/architecture.svg is, so the UI can serve it as a static asset.
    """

    from agent_framework import WorkflowViz

    destination.parent.mkdir(parents=True, exist_ok=True)
    produced = Path(WorkflowViz(_app_workflow()).save_svg(str(destination)))
    return produced


def _find_block(text: str, marker: str, path: Path) -> re.Match[str]:
    """Exactly one well-formed block, or a hard failure.

    Silently updating the first of several duplicates, or reporting "no
    marker" for a block whose end tag is missing, both look like success and
    leave the doc wrong.
    """

    starts = text.count(f"<!-- {marker}:start -->")
    ends = text.count(f"<!-- {marker}:end -->")
    if starts != 1 or ends != 1:
        raise ValueError(
            f"{path.name}: expected exactly one {marker} start and end marker, "
            f"found {starts} start and {ends} end"
        )
    found = _pattern(marker).search(text)
    if found is None:
        raise ValueError(f"{path.name}: {marker} end marker appears before its start marker")
    return found


def committed(path: Path, marker: str) -> str | None:
    """The mermaid currently in the doc, or None if the block is absent."""

    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if f"<!-- {marker}:start -->" not in text:
        return None
    body = _find_block(text, marker, path).group(0)
    fence = re.search(r"```mermaid\n(.*?)\n```", body, re.DOTALL)
    return fence.group(1).strip() if fence else None


def write(path: Path, marker: str, mermaid: str) -> bool:
    """Replace the marked block. Returns True if the file changed."""

    text = path.read_text(encoding="utf-8")
    found = _find_block(text, marker, path)
    replaced = text[: found.start()] + _block(marker, mermaid) + text[found.end() :]
    if replaced == text:
        return False
    path.write_text(replaced, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update the docs in place.")
    parser.add_argument(
        "--svg",
        action="store_true",
        help="Also write the app graph SVG the UI serves.",
    )
    args = parser.parse_args()

    changed = 0
    problems = 0
    if args.svg:
        out = save_app_svg(REPO_ROOT / "apps" / "web" / "public" / "workflow-graph.svg")
        print(f"  wrote {out.relative_to(REPO_ROOT)}")

    for key, marker, path in DIAGRAMS:
        mermaid = render(key)
        if not args.write:
            print(f"--- {key} -> {path.name} ({marker}) ---")
            print(mermaid)
            print()
            continue
        try:
            if write(path, marker, mermaid):
                changed += 1
                print(f"  updated {path.name} ({marker})")
        except (OSError, ValueError) as exc:
            problems += 1
            print(f"  [fail] {exc}", file=sys.stderr)

    if args.write:
        print(f"\n{changed} diagram(s) updated.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
