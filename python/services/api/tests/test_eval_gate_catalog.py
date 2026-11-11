"""The offline gate must actually run the checks its docstring advertises.

`score_envelope` takes `allowed` as an optional argument and skips catalog
membership entirely when it is absent. `main()` used to call it without one,
so an envelope citing an invented resource or goal ID passed the gate while
the module docstring claimed "allowed IDs" was among the checks. A gate that
silently does less than it says is worse than no gate.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_evals  # type: ignore[import-not-found]  # noqa: E402


def _envelope(**recommendation: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dealer_group_id": "GROUP-A",
        "citations": [{"dealer_group_id": "GROUP-A"}],
        "goal_suggestions": [],
        "strategy_suggestions": [],
        "resource_matches": [],
    }
    base.update(recommendation)
    return {
        "status": "ok",
        "provider_model": "test",
        "agent_trace": [],
        "recommendation": base,
    }


def test_allowed_catalog_is_populated() -> None:
    catalog = run_evals._allowed_catalog()
    assert catalog["goals"], "no goal IDs -> the check cannot fail"
    assert catalog["strategies"], "no strategy IDs -> the check cannot fail"
    # Absent entirely until 2026-09-16, so `_check_catalog` skipped
    # resource_matches for every case and an invented id passed the gate.
    assert catalog["resources"], "no resource IDs -> the check cannot fail"


def test_invented_resource_id_fails_the_gate() -> None:
    """resource_matches holds objects, so this also covers the is_object branch."""

    result = run_evals.score_envelope(
        "neg",
        _envelope(resource_matches=[{"id": "RES-invented-999"}]),
        allowed=run_evals._allowed_catalog(),
    )
    assert any("outside the allowed catalog" in f for f in result.failures), result.failures


@pytest.mark.parametrize(
    ("field", "invented"),
    [
        ("goal_suggestions", "GOAL-invented-999"),
        ("strategy_suggestions", "ST-invented-999"),
    ],
)
def test_invented_ids_fail_the_gate(field: str, invented: str) -> None:
    result = run_evals.score_envelope(
        "neg",
        _envelope(**{field: [invented]}),
        allowed=run_evals._allowed_catalog(),
    )
    assert any("outside the allowed catalog" in f for f in result.failures), result.failures


def test_real_ids_pass_the_catalog_check() -> None:
    catalog = run_evals._allowed_catalog()
    result = run_evals.score_envelope(
        "pos",
        _envelope(
            goal_suggestions=[sorted(catalog["goals"])[0]],
            resource_matches=[{"id": sorted(catalog["resources"])[0]}],
        ),
        allowed=catalog,
    )
    assert not any("outside the allowed catalog" in f for f in result.failures), result.failures
