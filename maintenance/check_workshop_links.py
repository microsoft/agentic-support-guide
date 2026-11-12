"""Check that every relative markdown link in the repo resolves.

Broken cross-references are the fastest way to lose a room, and they are
trivial to catch automatically.

Scoped to `workshop/` only at first, which meant broken links in `docs/` and
the root README went unnoticed - including ADRs pointing at a script that had
been deleted. A link's `#anchor` is checked too: a heading renamed in one
module silently breaks every "see section 6" that points at it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEARCH_ROOTS = (
    "workshop",
    "docs",
    "agents",
    "evals",
    "python",
    "dotnet",
    "apps",
    "conformance",
    "demo",
    "maintenance",
)
EXCLUDED_DIR_PARTS = {".venv", "node_modules", ".terraform", "__pycache__", "dist", "bin", "obj"}

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
EXPLICIT_ID = re.compile(r"""\b(?:id|name)=["']([^"']+)["']""")
FENCE = re.compile(r"^\s*(```|~~~)")
# GitHub's own line anchors (#L10, #L10-L20) are not headings.
LINE_ANCHOR = re.compile(r"^L\d+(-L\d+)?$")


def _prose_lines(text: str) -> list[str]:
    """The lines a reader sees as prose; fenced code is not rendered as links."""

    lines: list[str] = []
    in_code = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_code = not in_code
            continue
        if not in_code:
            lines.append(line)
    return lines


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""

    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text).replace("`", "")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s", "-", text)


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for line in _prose_lines(path.read_text(encoding="utf-8")):
        found.update(EXPLICIT_ID.findall(line))
        heading = HEADING.match(line)
        if not heading:
            continue
        base = slug(heading.group(1))
        count = seen.get(base, 0)
        seen[base] = count + 1
        found.add(base if count == 0 else f"{base}-{count}")
    return found


def _markdown_files(root: Path = REPO_ROOT) -> list[Path]:
    files = [p for p in root.glob("*.md") if p.is_file()]
    for name in SEARCH_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        files.extend(p for p in base.rglob("*.md") if not EXCLUDED_DIR_PARTS.intersection(p.parts))
    return sorted(set(files))


def check(files: list[Path], root: Path = REPO_ROOT) -> tuple[int, int, list[str]]:
    """(links checked, anchors checked, problems) for these markdown files."""

    broken: list[str] = []
    links = 0
    anchored = 0
    cache: dict[Path, set[str]] = {}
    for md in files:
        for line in _prose_lines(md.read_text(encoding="utf-8")):
            for raw in LINK.findall(line):
                if raw.startswith(("http://", "https://", "mailto:")):
                    continue
                target, _, anchor = raw.partition("#")
                target = target.strip()
                if target:
                    links += 1
                    resolved = (md.parent / target).resolve()
                    if not resolved.exists():
                        broken.append(f"{md.relative_to(root)} -> {target}")
                        continue
                else:
                    resolved = md
                if not anchor or resolved.suffix.lower() != ".md" or LINE_ANCHOR.match(anchor):
                    continue
                anchored += 1
                if resolved not in cache:
                    cache[resolved] = anchors(resolved)
                if anchor.lower() not in cache[resolved]:
                    broken.append(f"{md.relative_to(root)} -> {raw} (no such heading)")
    return links, anchored, broken


def main() -> int:
    files = _markdown_files()
    links, anchored, broken = check(files)

    print(f"Checked {links} relative link(s) and {anchored} anchor(s) across {len(files)} file(s).")
    if broken:
        print(f"\n{len(broken)} broken link(s):", file=sys.stderr)
        for item in broken:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("All relative links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
