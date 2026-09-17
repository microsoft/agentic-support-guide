"""Appointment / escalation / follow-up aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from .mock_data import OperationsRecord
from .models import OperationsSummary, TrendPoint


@dataclass(frozen=True)
class OperationsSeries:
    """One dealership's operational history, in period order."""

    periods: tuple[str, ...]
    appointment_attendance_rate: tuple[float, ...]
    escalations: tuple[int, ...]
    followup_completion: tuple[float, ...]
    record_count: int

    def is_empty(self) -> bool:
        return not self.periods


def series_for(records: list[OperationsRecord], dealership_id: str) -> OperationsSeries:
    """The operational time series the analyst reasons over."""

    rows = [r for r in records if r.dealership_id == dealership_id]
    by_period: dict[str, list[OperationsRecord]] = defaultdict(list)
    for row in rows:
        by_period[row.period].append(row)
    periods = tuple(sorted(by_period))

    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 3)

    return OperationsSeries(
        periods=periods,
        appointment_attendance_rate=tuple(
            _mean([r.appointment_attendance_rate for r in by_period[p]]) for p in periods
        ),
        escalations=tuple(
            round(sum(r.escalations for r in by_period[p]) / len(by_period[p])) for p in periods
        ),
        followup_completion=tuple(
            _mean([r.followup_completion for r in by_period[p]]) for p in periods
        ),
        record_count=len(rows),
    )


def _trend(
    records: list[OperationsRecord],
    value: Callable[[OperationsRecord], float],
    *,
    scale: float = 1.0,
    digits: int = 1,
) -> list[TrendPoint]:
    by_period: dict[str, list[float]] = defaultdict(list)
    for r in records:
        by_period[r.period].append(value(r))
    return [
        TrendPoint(period=period, value=round(sum(v) / len(v) * scale, digits))
        for period, v in sorted(by_period.items())
    ]


def _average(points: list[TrendPoint]) -> float:
    return sum(pt.value for pt in points) / len(points)


def summarize(records: list[OperationsRecord]) -> OperationsSummary:
    # Rates are stored 0-1 and shown as percentages.
    attendance = _trend(records, lambda r: r.appointment_attendance_rate, scale=100.0)
    escalations = _trend(records, lambda r: r.escalations, digits=2)
    followup = _trend(records, lambda r: r.followup_completion)

    highlights: list[str] = []
    if attendance:
        highlights.append(
            "Average booked appointments attended across periods: "
            f"{_average(attendance):.1f}% (synthetic)."
        )
    if escalations:
        highlights.append(
            f"Average escalations per dealership-period: {_average(escalations):.2f} (synthetic)."
        )
    if followup:
        highlights.append(f"Average follow-up completion: {_average(followup):.1f} (synthetic).")

    return OperationsSummary(
        attendance_trend=attendance,
        escalation_trend=escalations,
        engagement_trend=followup,
        highlights=highlights,
        total_records=len(records),
    )
