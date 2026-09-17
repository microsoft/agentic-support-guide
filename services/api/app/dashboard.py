"""Dashboard KPI aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable

from .mock_data import AreaScoreRecord, Dealership, OperationsRecord
from .models import AreaSlice, DashboardSummary, KpiCard, TrendPoint


def _mean_by[T](
    records: Iterable[T],
    key: Callable[[T], str],
    value: Callable[[T], float],
) -> list[tuple[str, float]]:
    """Group by `key`, average `value`, return pairs sorted by key.

    Period labels sort chronologically because they are ISO-style "2026-04",
    so sorting the keys is enough to order a trend line.
    """

    grouped: dict[str, list[float]] = defaultdict(list)
    for record in records:
        grouped[key(record)].append(value(record))
    return [(k, round(sum(v) / len(v), 1)) for k, v in sorted(grouped.items())]


def _kpi_cards(dealerships: list[Dealership]) -> list[KpiCard]:
    total = len(dealerships)
    flagged = sum(1 for d in dealerships if d.flagged)
    # The caller passes the full roster today, but a filtered one would make
    # these divisions a 500. Guard them like _band_distribution does.
    avg_process_score = (
        round(sum(d.process_score for d in dealerships) / total, 1) if total else 0.0
    )
    avg_attendance = (
        round(sum(d.appointment_attendance_rate for d in dealerships) / total * 100, 1)
        if total
        else 0.0
    )

    # The deltas are fixed illustrative values. The fixtures hold a single
    # snapshot, so there is no prior period to compare against.
    return [
        KpiCard(
            id="kpi-dealerships",
            label="Active Dealerships",
            value=float(total),
            unit="count",
            delta=0.0,
            trend="steady",
        ),
        KpiCard(
            id="kpi-flagged",
            label="Flagged for Support",
            value=float(flagged),
            unit="count",
            delta=round((flagged / total) * 100, 1),
            trend="watch",
        ),
        KpiCard(
            id="kpi-process-score",
            label="Avg Process Score",
            value=avg_process_score,
            unit="index",
            delta=1.2,
            trend="up",
        ),
        KpiCard(
            id="kpi-appointments",
            label="Appointments Attended",
            value=avg_attendance,
            unit="percent",
            delta=-0.4,
            trend="down",
        ),
    ]


def build_summary(
    dealerships: list[Dealership],
    area_scores: list[AreaScoreRecord],
    operations: list[OperationsRecord],
) -> DashboardSummary:
    return DashboardSummary(
        kpi_cards=_kpi_cards(dealerships),
        process_score_trend=[
            TrendPoint(period=period, value=value)
            for period, value in _mean_by(area_scores, lambda r: r.period, lambda r: r.score)
        ],
        area_distribution=[
            AreaSlice(process_area=area, value=value)
            for area, value in _mean_by(area_scores, lambda r: r.process_area, lambda r: r.score)
        ],
        engagement_trend=[
            TrendPoint(period=period, value=value)
            for period, value in _mean_by(
                operations, lambda r: r.period, lambda r: r.followup_completion
            )
        ],
        notes=[
            "All values are synthetic and generated locally.",
            "Trends are illustrative only; not real benchmarks or determinations.",
        ],
    )
