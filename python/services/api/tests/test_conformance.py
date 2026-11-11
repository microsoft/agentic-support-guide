"""The conformance goldens must describe what this code does today.

The .NET track is tested against `conformance/goldens/`. Those files are
recorded from this app, so a behaviour change here that is not re-recorded
would leave the other track conforming to something that no longer exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from .conformance_cases import build_goldens, render

GOLDENS = Path(__file__).resolve().parents[4] / "conformance" / "goldens"
REGENERATE = "python python/scripts/generate_conformance.py --write"


@pytest.fixture(scope="module")
def goldens() -> dict[str, Any]:
    return build_goldens()


def test_every_golden_is_current(goldens: dict[str, Any]) -> None:
    stale = [
        name
        for name, content in goldens.items()
        if not (GOLDENS / name).is_file()
        or (GOLDENS / name).read_text(encoding="utf-8") != render(content)
    ]
    assert not stale, f"stale goldens: {stale}. Regenerate with: {REGENERATE}"


def test_no_golden_is_orphaned(goldens: dict[str, Any]) -> None:
    on_disk = {p.relative_to(GOLDENS).as_posix() for p in GOLDENS.rglob("*") if p.is_file()}
    orphaned = sorted(on_disk - set(goldens))
    assert not orphaned, f"goldens nothing produces: {orphaned}. Regenerate with: {REGENERATE}"
