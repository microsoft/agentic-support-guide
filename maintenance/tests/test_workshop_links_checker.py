"""The link checker must catch a dead anchor, not only a dead file.

Before it checked anchors, a renamed heading broke every "see section 6"
pointing at it while the check stayed green.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "maintenance" / "check_workshop_links.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_workshop_links", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


links = _load_checker()


def test_slug_matches_github_for_punctuated_headings() -> None:
    assert links.slug("6. Optional — run the same steps as a pipeline") == (
        "6-optional--run-the-same-steps-as-a-pipeline"
    )
    heading = "`--expect-evidence` and [Module 1](m1.md)"
    assert links.slug(heading) == "--expect-evidence-and-module-1"


def test_repeated_headings_get_numbered_anchors(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# Setup\n\n## Check yourself\n\n## Check yourself\n", encoding="utf-8")
    assert {"setup", "check-yourself", "check-yourself-1"} <= links.anchors(doc)


def test_a_dead_anchor_fails_and_a_live_one_passes(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# Title\n\n## Real section\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text(
        "[ok](target.md#real-section) [also ok](#here)\n"
        "[gone](target.md#renamed-section)\n\n## Here\n",
        encoding="utf-8",
    )

    checked, anchored, broken = links.check([source], root=tmp_path)

    assert (checked, anchored) == (2, 3)
    assert broken == ["source.md -> target.md#renamed-section (no such heading)"]


def test_links_inside_fenced_code_are_not_checked(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("```markdown\n[example](missing.md#nowhere)\n```\n", encoding="utf-8")
    assert links.check([source], root=tmp_path) == (0, 0, [])


def test_the_repo_has_no_broken_links_or_anchors() -> None:
    _, _, broken = links.check(links._markdown_files())
    assert broken == []
