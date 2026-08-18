"""Assessment aggregation module."""

from __future__ import annotations

from collections import Counter, defaultdict

from .mock_data import AssessmentRecord
from .models import (
    AssessmentsSummary,
    DomainTrend,
    ProficiencyBucket,
    TrendPoint,
)

PROFICIENCY_ORDER: tuple[str, ...] = ("Emerging", "Approaching", "Proficient", "Advanced")


def summarize(
    records: list[AssessmentRecord],
    school: str | None,
    grade: str | None,
    domain: str | None,
    group: str | None,
) -> AssessmentsSummary:
    filtered = [
        r
        for r in records
        if (school is None or r.school_id == school)
        and (grade is None or str(r.grade) == grade)
        and (domain is None or r.domain == domain)
        and (group is None or r.group == group)
    ]

    counts = Counter(r.proficiency for r in filtered)
    total = len(filtered)
    distribution = [
        ProficiencyBucket(
            label=label,
            count=counts.get(label, 0),
            percent=round((counts.get(label, 0) / total) * 100, 1) if total else 0.0,
        )
        for label in PROFICIENCY_ORDER
    ]

    trend_map: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in filtered:
        trend_map[r.domain][r.period].append(r.score)
    domain_trends = [
        DomainTrend(
            domain=dom,
            points=[
                TrendPoint(period=p, value=round(sum(scores) / len(scores), 1))
                for p, scores in sorted(periods.items())
            ],
        )
        for dom, periods in sorted(trend_map.items())
    ]

    proficient_pct = next((b.percent for b in distribution if b.label == "Proficient"), 0.0)
    advanced_pct = next((b.percent for b in distribution if b.label == "Advanced"), 0.0)
    emerging_pct = next((b.percent for b in distribution if b.label == "Emerging"), 0.0)

    performance_summary = (
        f"Across {total} synthetic assessment records, {proficient_pct + advanced_pct:.1f}% "
        f"are Proficient or Advanced and {emerging_pct:.1f}% are Emerging. "
        "This is illustrative aggregation, not a real benchmark."
    )

    bullets: list[str] = []
    if emerging_pct > 25:
        bullets.append(
            "Consider targeted small-group instruction for learners in the Emerging band."
        )
    if advanced_pct > 25:
        bullets.append("Review acceleration options for consistently Advanced learners.")
    if total and proficient_pct + advanced_pct < 40:
        bullets.append("Aggregate proficiency is below 40%; review core-instruction cadence.")
    if not bullets:
        bullets.append("No rule-based flags triggered on the current filter selection.")

    table_rows: list[dict[str, str | int | float]] = [
        {
            "record_id": r.record_id,
            "learner_id": r.learner_id,
            "school_id": r.school_id,
            "grade": r.grade,
            "group": r.group,
            "domain": r.domain,
            "proficiency": r.proficiency,
            "score": r.score,
            "period": r.period,
        }
        for r in filtered[:100]
    ]

    return AssessmentsSummary(
        filters_applied={
            "school": school,
            "grade": grade,
            "domain": domain,
            "group": group,
        },
        total_records=total,
        proficiency_distribution=distribution,
        domain_trends=domain_trends,
        recommendation_bullets=bullets,
        performance_summary=performance_summary,
        generated_by="Generated from local rules over synthetic data.",
        table_rows=table_rows,
    )
