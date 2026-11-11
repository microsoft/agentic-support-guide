from __future__ import annotations

import json
from collections import Counter, defaultdict

from app.config import COUNTS
from app.mock_data import (
    PROCESS_AREAS,
    build_area_scores,
    build_audit_rows,
    build_dealerships,
    build_operations,
    build_resources,
    build_seeded_plan_specs,
)


def test_counts_match_spec() -> None:
    dealerships = build_dealerships()
    assert len(dealerships) == COUNTS.dealerships
    assert len(build_area_scores(dealerships)) == (
        COUNTS.dealerships * COUNTS.score_periods * len(PROCESS_AREAS)
    )
    assert len(build_operations(dealerships)) == COUNTS.dealerships * COUNTS.score_periods
    assert len(build_resources()) == COUNTS.resources
    assert len(build_audit_rows()) == COUNTS.audit_events
    assert len(build_seeded_plan_specs()) == COUNTS.seeded_plans


def test_every_dealership_has_an_operations_record_for_every_period() -> None:
    """A random 150 records over 720 slots gave most dealerships one datapoint.

    One datapoint cannot show a trend, so the analyst had nothing operational
    to reason about.
    """

    dealerships = build_dealerships()
    seen = {(r.dealership_id, r.period) for r in build_operations(dealerships)}
    assert len(seen) == COUNTS.dealerships * COUNTS.score_periods
    assert {d.dealership_id for d in dealerships} == {key[0] for key in seen}


def test_every_dealership_period_scores_every_area_exactly_once() -> None:
    """The dataset claims every review scores every area; it did not.

    Random sampling left 253 of 319 subject-periods holding a single area
    and none holding all six, so no cross-area comparison was possible.
    """

    dealerships = build_dealerships()
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in build_area_scores(dealerships):
        groups[(record.dealership_id, record.period)].append(record.process_area)

    assert len(groups) == COUNTS.dealerships * COUNTS.score_periods
    assert {d.dealership_id for d in dealerships} == {key[0] for key in groups}
    for key, areas in groups.items():
        assert Counter(areas) == Counter(PROCESS_AREAS), f"incomplete or duplicated: {key}"


def test_scores_carry_a_trend_rather_than_noise() -> None:
    """A flat random series gives the analyst agent nothing to detect."""

    dealerships = build_dealerships()
    by_dealership: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for record in build_area_scores(dealerships):
        by_dealership[record.dealership_id][record.period].append(record.score)

    deltas = []
    for periods in by_dealership.values():
        ordered = [sum(v) / len(v) for _, v in sorted(periods.items())]
        deltas.append(ordered[-1] - ordered[0])

    # Both directions must occur, or the demo only ever tells one story.
    assert any(delta >= 5.0 for delta in deltas), "no dealership improves"
    assert any(delta <= -5.0 for delta in deltas), "no dealership declines"
    moved = sum(1 for delta in deltas if abs(delta) >= 5.0)
    assert moved >= len(deltas) // 3, f"only {moved} of {len(deltas)} dealerships move"


def test_scores_stay_off_the_clamp_bounds() -> None:
    """Saturating at 99 flattened strong dealerships into a straight line."""

    records = build_area_scores(build_dealerships())
    assert not [r for r in records if r.score in (1, 99)]


def test_the_cohort_average_moves_across_periods() -> None:
    """Centred per-dealership drift cancels out and flattened every trend chart."""

    by_period: dict[str, list[int]] = defaultdict(list)
    for record in build_area_scores(build_dealerships()):
        by_period[record.period].append(record.score)
    means = [sum(v) / len(v) for _, v in sorted(by_period.items())]
    assert means[-1] - means[0] >= 3.0, f"cohort trend is flat: {means}"


def test_two_invocations_produce_identical_json() -> None:
    def snapshot() -> str:
        dealerships = build_dealerships()
        payload = {
            "dealerships": [d.__dict__ for d in dealerships],
            "assessments": [record.__dict__ for record in build_area_scores(dealerships)],
            "behavior": [record.__dict__ for record in build_operations(dealerships)],
            "resources": [record.__dict__ for record in build_resources()],
            "audit": [record.__dict__ for record in build_audit_rows()],
            "seeded_plans": [record.__dict__ for record in build_seeded_plan_specs()],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    first = snapshot()
    second = snapshot()
    assert first == second, "Mock data factories must be deterministic"
    assert first.encode("utf-8") == second.encode("utf-8")


def test_dealership_ids_are_synthetic() -> None:
    for dealership in build_dealerships():
        assert dealership.dealership_id.startswith("DLR-")
        assert dealership.display_label.startswith("Dealership ")
