"""Check that every relative markdown link in the workshop resolves.

Broken cross-references are the fastest way to lose a room, and they are
trivial to catch automatically.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP = REPO_ROOT / "workshop"

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    broken: list[str] = []
    checked = 0

    for md in sorted(WORKSHOP.glob("*.md")):
        for raw in LINK.findall(md.read_text(encoding="utf-8")):
            target = raw.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            if not (md.parent / target).resolve().exists():
                broken.append(f"{md.relative_to(REPO_ROOT)} -> {target}")

    print(f"Checked {checked} relative link(s) across {len(list(WORKSHOP.glob('*.md')))} file(s).")
    if broken:
        print(f"\n{len(broken)} broken link(s):", file=sys.stderr)
        for item in broken:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("All relative links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
