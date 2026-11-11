"""Write or check the conformance goldens the .NET track is tested against.

    python python/scripts/generate_conformance.py            # check; exit 1 if stale
    python python/scripts/generate_conformance.py --write    # regenerate

The goldens are recorded by running this track's app, so they are only as
current as the Python code. `tests/test_conformance.py` runs the same check
on every pull request.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TRACK_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = TRACK_ROOT.parent
GOLDENS = REPO_ROOT / "conformance" / "goldens"
sys.path.insert(0, str(TRACK_ROOT / "services" / "api"))

from tests.conformance_cases import build_goldens, render  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Rewrite conformance/goldens.")
    args = parser.parse_args()

    goldens = build_goldens()
    on_disk = {p.relative_to(GOLDENS).as_posix() for p in GOLDENS.rglob("*") if p.is_file()}

    if args.write:
        for name in sorted(on_disk - set(goldens)):
            (GOLDENS / name).unlink()
            print(f"  removed {name}")
        for name, content in goldens.items():
            path = GOLDENS / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(render(content).encode("utf-8"))
        print(f"Wrote {len(goldens)} golden(s) to {GOLDENS.relative_to(REPO_ROOT).as_posix()}.")
        return 0

    stale = [
        name
        for name, content in goldens.items()
        if name not in on_disk or (GOLDENS / name).read_text(encoding="utf-8") != render(content)
    ]
    orphaned = sorted(on_disk - set(goldens))
    for name in stale:
        print(f"  [stale]    {name}")
    for name in orphaned:
        print(f"  [orphaned] {name}")
    if stale or orphaned:
        print("\nRegenerate with: python python/scripts/generate_conformance.py --write")
        return 1
    print(f"All {len(goldens)} golden(s) are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
