"""Check that every relative markdown link in the repo resolves.

Broken cross-references are the fastest way to lose a room, and they are
trivial to catch automatically.

Scoped to `workshop/` only at first, which meant broken links in `docs/` and
the root README went unnoticed - including ADRs pointing at a script that had
been deleted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEARCH_ROOTS = ("workshop", "docs", "agents", "contracts", "infra", "evals", "services")
EXCLUDED_DIR_PARTS = {".venv", "node_modules", ".terraform", "__pycache__", "dist"}

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    files = [p for p in REPO_ROOT.glob("*.md") if p.is_file()]
    for root in SEARCH_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        files.extend(p for p in base.rglob("*.md") if not EXCLUDED_DIR_PARTS.intersection(p.parts))
    return sorted(set(files))


def main() -> int:
    broken: list[str] = []
    checked = 0
    files = _markdown_files()

    for md in files:
        for raw in LINK.findall(md.read_text(encoding="utf-8")):
            target = raw.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            if not (md.parent / target).resolve().exists():
                broken.append(f"{md.relative_to(REPO_ROOT)} -> {target}")

    print(f"Checked {checked} relative link(s) across {len(files)} file(s).")
    if broken:
        print(f"\n{len(broken)} broken link(s):", file=sys.stderr)
        for item in broken:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("All relative links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
