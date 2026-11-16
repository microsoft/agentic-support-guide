"""The workshop samples are taught as correct, so they are tested as correct.

Three kinds of check:

- behaviour: each conditional edge routes to the right terminal executor, and
  exactly one of them ever fires;
- the rule sample 7 teaches: a mutable message really does make a stale
  condition fire, and the frozen version really does not;
- drift: the Mermaid committed in the workshop still matches what
  `WorkflowViz` renders from the code.

The drift check alone is not enough. A condition can change while the
rendered diagram stays byte-identical, because the renderer labels every
conditional edge "conditional".
"""

from __future__ import annotations

import html
import importlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Never

import pytest
from agent_framework import Workflow, WorkflowBuilder, WorkflowContext, executor

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(directory: str, module_name: str) -> Any:
    """Import from a sibling directory without leaving it on `sys.path`.

    Left in place, `workshop/python/code/` and `python/scripts/` would shadow real imports for
    every test module that runs after this one.
    """

    path = str(REPO_ROOT / directory)
    sys.path.insert(0, path)
    try:
        return importlib.import_module(module_name)
    finally:
        if path in sys.path:
            sys.path.remove(path)


repair = _load("workshop/python/code", "07_conditional_repair")
first_workflow = _load("workshop/python/code", "05_first_workflow")
render_workflow_diagram = _load("python/scripts", "render_workflow_diagram")


async def _run(tag: str) -> list[str]:
    events = await repair.build_workflow().run(f"{tag} first reply is slow")
    return [str(o) for o in events.get_outputs()]


@pytest.mark.asyncio
async def test_first_workflow_runs_offline() -> None:
    events = await first_workflow.build_workflow().run("  Our first REPLY is   slow ")
    assert events.get_outputs() == ["routed -> lead-response: our first reply is slow"]


@pytest.mark.asyncio
async def test_clean_draft_is_accepted_on_the_first_attempt() -> None:
    outputs = await _run(repair.NEVER_INVENTS)
    assert len(outputs) == 1
    assert outputs[0].startswith("OK after 1 attempt(s)")


@pytest.mark.asyncio
async def test_bad_citation_is_repaired_and_then_accepted() -> None:
    outputs = await _run(repair.INVENTS_ONCE)
    assert len(outputs) == 1
    assert outputs[0].startswith("OK after 2 attempt(s)")
    assert "EV-999" not in outputs[0]


@pytest.mark.asyncio
async def test_exhausted_repair_refuses_and_returns_no_recommendation() -> None:
    """The branch the sample claims to teach has to be reachable."""

    outputs = await _run(repair.ALWAYS_INVENTS)
    assert len(outputs) == 1
    assert outputs[0].startswith(f"REFUSED after {repair.MAX_ATTEMPTS} attempt(s)")
    assert "Assign a named advisor" not in outputs[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tag",
    [repair.NEVER_INVENTS, repair.INVENTS_ONCE, repair.ALWAYS_INVENTS],
)
async def test_exactly_one_terminal_executor_fires_per_run(tag: str) -> None:
    assert len(await _run(tag)) == 1


# --- the rule sample 7 teaches --------------------------------------------
#
# Outgoing edges are handed the same message object and evaluate their
# conditions independently. This workflow is sample 7's shape with a mutable
# message, so the documented bug is reproduced rather than asserted.


@dataclass
class _Mutable:
    """Sample 7's Draft, without the `frozen=True`."""

    allowed: tuple[str, ...] = ("EV-101",)
    cited: tuple[str, ...] = ()
    attempts: int = 0
    issues: list[str] = field(default_factory=list)


@executor(id="m_recommend")
async def _m_recommend(draft: _Mutable, ctx: WorkflowContext[_Mutable]) -> None:
    draft.attempts += 1
    # Note what this does NOT touch: `issues`. Only the validator sets those,
    # which is why a stale edge can still be holding the old ones.
    draft.cited = ("EV-999",) if draft.attempts == 1 else ("EV-101",)
    await ctx.send_message(draft)


@executor(id="m_validate")
async def _m_validate(draft: _Mutable, ctx: WorkflowContext[_Mutable]) -> None:
    draft.issues = [c for c in draft.cited if c not in set(draft.allowed)]
    await ctx.send_message(draft)


@executor(id="m_accept")
async def _m_accept(draft: _Mutable, ctx: WorkflowContext[Never, str]) -> None:
    await ctx.yield_output("accepted")


@executor(id="m_give_up")
async def _m_give_up(draft: _Mutable, ctx: WorkflowContext[Never, str]) -> None:
    await ctx.yield_output("refused")


def _mutable_workflow() -> Workflow:
    return (
        WorkflowBuilder(start_executor=_m_recommend, name="mutable")
        .add_edge(_m_recommend, _m_validate)
        .add_edge(_m_validate, _m_accept, condition=lambda d: not d.issues)
        .add_edge(_m_validate, _m_recommend, condition=lambda d: bool(d.issues) and d.attempts < 2)
        .add_edge(_m_validate, _m_give_up, condition=lambda d: bool(d.issues) and d.attempts >= 2)
        .build()
    )


@pytest.mark.asyncio
async def test_a_mutated_message_makes_a_stale_condition_fire() -> None:
    """Reproduces the bug sample 7 warns about, so the warning is not folklore.

    The repair round bumps `attempts` on the object the `exhausted` edge is
    still holding, so that edge fires as well and one run yields two answers.
    """

    events = await _mutable_workflow().run(_Mutable())
    outputs = sorted(str(o) for o in events.get_outputs())

    assert outputs == ["accepted", "refused"], (
        "expected the documented double-output bug; if this now yields one "
        "output the framework changed and sample 7's lesson needs rewriting"
    )


@pytest.mark.asyncio
async def test_the_frozen_version_of_the_same_flow_yields_one_answer() -> None:
    """The fix sample 7 prescribes, over the same repair path."""

    assert len(await _run(repair.INVENTS_ONCE)) == 1


@pytest.mark.parametrize(("module_name", "marker", "path"), render_workflow_diagram.DIAGRAMS)
def test_committed_diagram_matches_the_built_workflow(
    module_name: str, marker: str, path: Path
) -> None:
    expected = render_workflow_diagram.render(module_name)
    actual = render_workflow_diagram.committed(path, marker)
    assert actual is not None, f"{path.name} has no <!-- {marker}:start --> block"
    assert actual == expected, (
        f"{path.name} is stale. Regenerate with:\n"
        "  python python/scripts/render_workflow_diagram.py --write"
    )


WEB_GRAPH_SVG = REPO_ROOT / "apps" / "web" / "src" / "assets" / "workflow-graph.svg"

Graph = tuple[set[str], set[tuple[str, str, bool]], set[str]]


def _dot_graph(dot: str) -> Graph:
    nodes: set[str] = set()
    edges: set[tuple[str, str, bool]] = set()
    starts: set[str] = set()
    for line in dot.splitlines():
        if edge := re.match(r'\s*"([^"]+)" -> "([^"]+)"(.*);', line):
            edges.add((edge[1], edge[2], "style=dashed" in edge[3]))
        elif node := re.match(r'\s*"([^"]+)" \[(.*)\];', line):
            nodes.add(node[1])
            if "fillcolor=lightgreen" in node[2]:
                starts.add(node[1])
    return nodes, edges, starts


def _svg_graph(svg: str) -> Graph:
    nodes: set[str] = set()
    edges: set[tuple[str, str, bool]] = set()
    starts: set[str] = set()
    node_pattern = r'class="node">\s*<title>(.*?)</title>\s*<polygon fill="([^"]*)"'
    for title, fill in re.findall(node_pattern, svg):
        nodes.add(html.unescape(title))
        if fill == "lightgreen":
            starts.add(html.unescape(title))
    for title, path in re.findall(r'class="edge">\s*<title>(.*?)</title>\s*<path ([^>]*)>', svg):
        source, target = html.unescape(title).split("->")
        edges.add((source, target, "stroke-dasharray" in path))
    return nodes, edges, starts


def test_web_graph_svg_matches_the_app_workflow() -> None:
    """The UI says its picture matches the graph a request runs; this keeps that true."""

    expected = _dot_graph(render_workflow_diagram.app_dot())
    assert expected[0], "parsed no nodes from the DOT export"
    assert _svg_graph(WEB_GRAPH_SVG.read_text(encoding="utf-8")) == expected, (
        f"{WEB_GRAPH_SVG.name} is stale. Regenerate with:\n"
        "  python python/scripts/render_workflow_diagram.py --dot | dot -Tsvg -o "
        "apps/web/src/assets/workflow-graph.svg"
    )
