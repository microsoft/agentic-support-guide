"""Process-area score aggregation module."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .mock_data import AreaScoreRecord
from .models import (
    AreaTrend,
    BandBucket,
    ScoresSummary,
    TrendPoint,
)

BAND_ORDER: tuple[str, ...] = ("At risk", "Developing", "On track", "Leading")

# The table is a preview, not an export. Returning 3600 rows to a browser to
# render a scrollable grid is not worth the payload.
MAX_TABLE_ROWS = 100


@dataclass(frozen=True)
class AreaSeries:
    """One dealership's score history, per process area, in period order.

    `scores_by_area` values line up positionally with `periods`, and a gap is
    `None` rather than a shortened tuple. A shortened tuple silently shifted
    later readings into earlier slots, so a June score read as May.
    """

    periods: tuple[str, ...]
    scores_by_area: dict[str, tuple[int | None, ...]]
    latest_band_by_area: dict[str, str]
    record_count: int
    duplicate_count: int = 0

    def is_empty(self) -> bool:
        return not self.periods


def series_for(records: list[AreaScoreRecord], dealership_id: str) -> AreaSeries:
    """The per-area time series the analyst reasons over.

    The analyst used to receive only a record *count*, so the cross-area and
    temporal comparison its instructions describe had nothing to work from.
    """

    rows = [r for r in records if r.dealership_id == dealership_id]
    periods = tuple(sorted({r.period for r in rows}))
    by_area: dict[str, dict[str, AreaScoreRecord]] = defaultdict(dict)
    duplicates = 0
    for row in rows:
        if row.period in by_area[row.process_area]:
            duplicates += 1
        by_area[row.process_area][row.period] = row

    scores_by_area = {
        area: tuple(by_period[p].score if p in by_period else None for p in periods)
        for area, by_period in sorted(by_area.items())
    }
    latest_band_by_area = {
        area: by_period[periods[-1]].band
        for area, by_period in sorted(by_area.items())
        if periods and periods[-1] in by_period
    }
    return AreaSeries(
        periods=periods,
        scores_by_area=scores_by_area,
        latest_band_by_area=latest_band_by_area,
        record_count=len(rows),
        duplicate_count=duplicates,
    )


def _filter(
    records: list[AreaScoreRecord],
    region: str | None,
    process_area: str | None,
    segment: str | None,
) -> list[AreaScoreRecord]:
    return [
        r
        for r in records
        if (region is None or r.region_id == region)
        and (process_area is None or r.process_area == process_area)
        and (segment is None or r.segment == segment)
    ]


def _band_distribution(records: list[AreaScoreRecord]) -> list[BandBucket]:
    counts = Counter(r.band for r in records)
    total = len(records)
    return [
        BandBucket(
            label=label,
            count=counts.get(label, 0),
            percent=round((counts.get(label, 0) / total) * 100, 1) if total else 0.0,
        )
        for label in BAND_ORDER
    ]


def _area_trends(records: list[AreaScoreRecord]) -> list[AreaTrend]:
    by_area: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_area[r.process_area][r.period].append(r.score)
    return [
        AreaTrend(
            process_area=area,
            points=[
                TrendPoint(period=period, value=round(sum(scores) / len(scores), 1))
                for period, scores in sorted(periods.items())
            ],
        )
        for area, periods in sorted(by_area.items())
    ]


def _percent(distribution: list[BandBucket], label: str) -> float:
    return next((b.percent for b in distribution if b.label == label), 0.0)


def _performance_summary(total: int, distribution: list[BandBucket]) -> str:
    healthy = _percent(distribution, "On track") + _percent(distribution, "Leading")
    return (
        f"Across {total} synthetic process-score records, {healthy:.1f}% "
        f"are On track or Leading and {_percent(distribution, 'At risk'):.1f}% are At risk. "
        "This is illustrative aggregation, not a real benchmark."
    )


def _recommendation_bullets(total: int, distribution: list[BandBucket]) -> list[str]:
    """Fixed thresholds over the filtered rows. No model is involved.

    This is what the dashboard shows before anyone asks for a plan, and it is
    worth contrasting with the agent workflow: same data, but these bullets
    cite no evidence and adapt to nothing.
    """

    at_risk = _percent(distribution, "At risk")
    leading = _percent(distribution, "Leading")
    healthy = _percent(distribution, "On track") + leading

    bullets: list[str] = []
    if at_risk > 25:
        bullets.append("Consider a focused coaching cycle for dealerships in the At risk band.")
    if leading > 25:
        bullets.append("Review what consistently Leading dealerships are doing differently.")
    if total and healthy < 40:
        bullets.append("Fewer than 40% are On track or better; review the process cadence.")
    return bullets or ["No rule-based flags triggered on the current filter selection."]


def _table_rows(records: list[AreaScoreRecord]) -> list[dict[str, str | int | float]]:
    return [
        {
            "record_id": r.record_id,
            "dealership_id": r.dealership_id,
            "region_id": r.region_id,
            "segment": r.segment,
            "process_area": r.process_area,
            "band": r.band,
            "score": r.score,
            "period": r.period,
        }
        for r in records[:MAX_TABLE_ROWS]
    ]


def summarize(
    records: list[AreaScoreRecord],
    region: str | None,
    process_area: str | None,
    segment: str | None,
) -> ScoresSummary:
    filtered = _filter(records, region, process_area, segment)
    distribution = _band_distribution(filtered)
    total = len(filtered)

    return ScoresSummary(
        filters_applied={
            "region": region,
            "process_area": process_area,
            "segment": segment,
        },
        total_records=total,
        band_distribution=distribution,
        area_trends=_area_trends(filtered),
        recommendation_bullets=_recommendation_bullets(total, distribution),
        performance_summary=_performance_summary(total, distribution),
        generated_by="Generated from local rules over synthetic data.",
        table_rows=_table_rows(filtered),
    )
