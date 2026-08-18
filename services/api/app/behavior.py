"""Behavior / attendance / engagement aggregation."""

from __future__ import annotations

from collections import defaultdict

from .mock_data import BehaviorRecord
from .models import BehaviorSummary, TrendPoint


def summarize(records: list[BehaviorRecord]) -> BehaviorSummary:
    by_period_attendance: dict[str, list[float]] = defaultdict(list)
    by_period_behavior: dict[str, list[int]] = defaultdict(list)
    by_period_engagement: dict[str, list[float]] = defaultdict(list)

    for r in records:
        by_period_attendance[r.period].append(r.attendance_rate)
        by_period_behavior[r.period].append(r.behavior_incidents)
        by_period_engagement[r.period].append(r.engagement_score)

    attendance = [
        TrendPoint(period=p, value=round(sum(v) / len(v) * 100, 1))
        for p, v in sorted(by_period_attendance.items())
    ]
    behavior = [
        TrendPoint(period=p, value=round(sum(v) / len(v), 2))
        for p, v in sorted(by_period_behavior.items())
    ]
    engagement = [
        TrendPoint(period=p, value=round(sum(v) / len(v), 1))
        for p, v in sorted(by_period_engagement.items())
    ]

    highlights: list[str] = []
    if attendance:
        avg_att = sum(pt.value for pt in attendance) / len(attendance)
        highlights.append(f"Average attendance across periods: {avg_att:.1f}% (synthetic).")
    if behavior:
        avg_beh = sum(pt.value for pt in behavior) / len(behavior)
        highlights.append(f"Average incidents per learner-period: {avg_beh:.2f} (synthetic).")
    if engagement:
        avg_eng = sum(pt.value for pt in engagement) / len(engagement)
        highlights.append(f"Average engagement index: {avg_eng:.1f} (synthetic).")

    return BehaviorSummary(
        attendance_trend=attendance,
        behavior_trend=behavior,
        engagement_trend=engagement,
        highlights=highlights,
        total_records=len(records),
    )
