"""Dashboard KPI aggregation."""

from __future__ import annotations

from collections import defaultdict

from .mock_data import AssessmentRecord, BehaviorRecord, Learner
from .models import DashboardSummary, DomainSlice, KpiCard, TrendPoint


def build_summary(
    learners: list[Learner],
    assessments: list[AssessmentRecord],
    behavior: list[BehaviorRecord],
) -> DashboardSummary:
    total_learners = len(learners)
    flagged = sum(1 for learner in learners if learner.flagged)
    avg_proficiency = round(
        sum(learner.proficiency_index for learner in learners) / total_learners, 1
    )
    avg_attendance = round(
        sum(learner.attendance_rate for learner in learners) / total_learners * 100, 1
    )

    kpi_cards = [
        KpiCard(
            id="kpi-learners",
            label="Active Learners",
            value=float(total_learners),
            unit="count",
            delta=0.0,
            trend="steady",
        ),
        KpiCard(
            id="kpi-flagged",
            label="Flagged for Support",
            value=float(flagged),
            unit="count",
            delta=round((flagged / total_learners) * 100, 1),
            trend="watch",
        ),
        KpiCard(
            id="kpi-proficiency",
            label="Avg Proficiency Index",
            value=avg_proficiency,
            unit="index",
            delta=1.2,
            trend="up",
        ),
        KpiCard(
            id="kpi-attendance",
            label="Avg Attendance",
            value=avg_attendance,
            unit="percent",
            delta=-0.4,
            trend="down",
        ),
    ]

    by_period_scores: dict[str, list[int]] = defaultdict(list)
    for a_record in assessments:
        by_period_scores[a_record.period].append(a_record.score)
    proficiency_trend = [
        TrendPoint(period=p, value=round(sum(v) / len(v), 1))
        for p, v in sorted(by_period_scores.items())
    ]

    by_domain_scores: dict[str, list[int]] = defaultdict(list)
    for a_record in assessments:
        by_domain_scores[a_record.domain].append(a_record.score)
    domain_distribution = [
        DomainSlice(domain=dom, value=round(sum(v) / len(v), 1))
        for dom, v in sorted(by_domain_scores.items())
    ]

    by_period_engagement: dict[str, list[float]] = defaultdict(list)
    for b_record in behavior:
        by_period_engagement[b_record.period].append(b_record.engagement_score)
    engagement_trend = [
        TrendPoint(period=p, value=round(sum(v) / len(v), 1))
        for p, v in sorted(by_period_engagement.items())
    ]

    notes = [
        "All values are synthetic and generated locally.",
        "Trends are illustrative only; not real benchmarks or determinations.",
    ]

    return DashboardSummary(
        kpi_cards=kpi_cards,
        proficiency_trend=proficiency_trend,
        domain_distribution=domain_distribution,
        engagement_trend=engagement_trend,
        notes=notes,
    )
