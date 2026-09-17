"""Deterministic mock data factories.

All randomness is seeded via `random.Random(SEED)`; never `random.random`
globally. All timestamps derive from `BASE_TIMESTAMP` with fixed offsets so
two invocations produce byte-identical JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import Random

from .config import BASE_TIMESTAMP, COUNTS, SEED

REGION_IDS: tuple[str, ...] = ("REG-001", "REG-002", "REG-003", "REG-004")
SEGMENT_IDS: tuple[str, ...] = ("SEG-VOLUME", "SEG-PREMIUM", "SEG-COMMERCIAL")

# Five measured process areas. `multi-area` is deliberately NOT here: it is a
# plan scope a user can request, not something a dealership is scored on.
# Scoring it produced a sixth "area" with its own independent value that sat
# outside the real five for 37 of 120 dealerships and skewed every aggregate.
PROCESS_AREAS: tuple[str, ...] = (
    "lead-response",
    "test-drive-conversion",
    "listing-completeness",
    "inventory-ageing",
    "price-data-freshness",
)

# Everything a plan can be requested for: the measured areas plus the
# cross-area scope.
CATEGORY_IDS: tuple[str, ...] = (*PROCESS_AREAS, "multi-area")

# Points per period the whole network gains. Individual drifts are centred and
# so cancel in aggregate, which left every dashboard trend line flat.
COHORT_DRIFT_PER_PERIOD = 0.9

# Six consecutive months ending at the current reporting month.
PERIOD_START_MONTH = 4


def period_label(index: int) -> str:
    """Roll into the next year rather than emitting "2026-13"."""

    month = PERIOD_START_MONTH + index
    return f"{2026 + (month - 1) // 12}-{(month - 1) % 12 + 1:02d}"


@dataclass(frozen=True)
class Dealership:
    dealership_id: str
    display_label: str
    region_id: str
    segment: str
    process_score: float
    appointment_attendance_rate: float
    followup_index: float
    engagement_index: float
    flagged: bool


@dataclass(frozen=True)
class AreaScoreRecord:
    record_id: str
    dealership_id: str
    region_id: str
    segment: str
    process_area: str
    band: str
    score: int
    period: str


@dataclass(frozen=True)
class OperationsRecord:
    record_id: str
    dealership_id: str
    region_id: str
    period: str
    appointment_attendance_rate: float
    escalations: int
    followup_completion: float


@dataclass(frozen=True)
class ResourceItem:
    resource_id: str
    label: str
    kind: str
    process_area: str
    tier: str


@dataclass(frozen=True)
class AuditRow:
    event_id: str
    timestamp: str
    endpoint: str
    context: str
    user: str
    provider_model: str
    duration_ms: int
    token_estimate: int
    status: str


def _base_dt() -> datetime:
    return datetime.strptime(BASE_TIMESTAMP, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _offset_iso(days: int, seconds: int = 0) -> str:
    ts = _base_dt() + timedelta(days=days, seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _band_label(score: int) -> str:
    if score < 40:
        return "At risk"
    if score < 60:
        return "Developing"
    if score < 80:
        return "On track"
    return "Leading"


def build_dealerships() -> list[Dealership]:
    rng = Random(SEED)
    dealerships: list[Dealership] = []
    for i in range(1, COUNTS.dealerships + 1):
        did = f"DLR-{i:04d}"
        label = f"Dealership {i:04d}"
        region = REGION_IDS[rng.randrange(len(REGION_IDS))]
        segment = SEGMENT_IDS[rng.randrange(len(SEGMENT_IDS))]
        process_score = round(rng.uniform(20.0, 95.0), 1)
        attendance = round(rng.uniform(0.72, 0.99), 3)
        followup = round(rng.uniform(30.0, 95.0), 1)
        engagement = round(rng.uniform(30.0, 95.0), 1)
        flagged = process_score < 45 or attendance < 0.85 or followup < 50
        dealerships.append(
            Dealership(
                dealership_id=did,
                display_label=label,
                region_id=region,
                segment=segment,
                process_score=process_score,
                appointment_attendance_rate=attendance,
                followup_index=followup,
                engagement_index=engagement,
                flagged=flagged,
            )
        )
    return dealerships


def build_area_scores(dealerships: list[Dealership]) -> list[AreaScoreRecord]:
    """One record per dealership, per period, per process area.

    This used to draw a random subject and a random area 400 times, which
    left 253 of 319 subject-periods holding a single area, 18 holding the
    same area twice, and not one holding all six. Nothing could compare a
    dealership across areas, which is the analysis the workshop demonstrates.

    Scores are built from a per-dealership baseline, a per-area offset and a
    per-dealership drift, so a trend is actually present to be found rather
    than being noise.
    """

    rng = Random(SEED + 1)
    records: list[AreaScoreRecord] = []
    sequence = 0
    for dealership in dealerships:
        # Compressed into a mid band so an area offset plus six periods of
        # drift still fit inside 1-99. Using the raw score pinned strong
        # dealerships against the ceiling and flattened the trend away.
        baseline = 28.0 + (dealership.process_score - 20.0) / 75.0 * 50.0
        area_offsets = {area: rng.uniform(-11.0, 11.0) for area in PROCESS_AREAS}
        drift = rng.uniform(-2.5, 2.5)
        midpoint = (COUNTS.score_periods - 1) / 2.0
        for index in range(COUNTS.score_periods):
            period = period_label(index)
            for area in PROCESS_AREAS:
                # Drift is centred on the midpoint so process_score stays the
                # dealership's average rather than their starting point. That
                # halves the headroom a trend needs, which is what let the
                # score band stay wide enough to populate every tier.
                raw = (
                    baseline
                    + area_offsets[area]
                    + (drift + COHORT_DRIFT_PER_PERIOD) * (index - midpoint)
                    + rng.uniform(-2.5, 2.5)
                )
                score = max(1, min(99, round(raw)))
                sequence += 1
                records.append(
                    AreaScoreRecord(
                        record_id=f"SCR-{sequence:05d}",
                        dealership_id=dealership.dealership_id,
                        region_id=dealership.region_id,
                        segment=dealership.segment,
                        process_area=area,
                        band=_band_label(score),
                        score=score,
                        period=period,
                    )
                )
    return records


def build_operations(dealerships: list[Dealership]) -> list[OperationsRecord]:
    """One record per dealership, per period.

    This used to draw 150 records at random across 720 dealership-periods, so
    a typical dealership had a single data point and the analyst could not see
    an operational trend at all.
    """

    rng = Random(SEED + 2)
    records: list[OperationsRecord] = []
    sequence = 0
    midpoint = (COUNTS.score_periods - 1) / 2.0
    for dealership in dealerships:
        attendance_drift = rng.uniform(-0.015, 0.015)
        followup_drift = rng.uniform(-2.0, 2.0)
        for index in range(COUNTS.score_periods):
            offset = index - midpoint
            attendance = dealership.appointment_attendance_rate + attendance_drift * offset
            attendance += rng.uniform(-0.01, 0.01)
            followup = dealership.followup_index + followup_drift * offset + rng.uniform(-2.0, 2.0)
            sequence += 1
            records.append(
                OperationsRecord(
                    record_id=f"OPS-{sequence:05d}",
                    dealership_id=dealership.dealership_id,
                    region_id=dealership.region_id,
                    period=period_label(index),
                    appointment_attendance_rate=round(max(0.5, min(1.0, attendance)), 3),
                    escalations=rng.randrange(0, 5),
                    followup_completion=round(max(1.0, min(99.0, followup)), 1),
                )
            )
    return records


def build_resources() -> list[ResourceItem]:
    rng = Random(SEED + 3)
    kinds = ("playbook", "checklist", "coaching-plan", "customer-message", "audit-kit")
    tiers = ("baseline", "focused", "intensive")
    items: list[ResourceItem] = []
    for i in range(1, COUNTS.resources + 1):
        area = PROCESS_AREAS[rng.randrange(len(PROCESS_AREAS))]
        kind = kinds[rng.randrange(len(kinds))]
        tier = tiers[rng.randrange(len(tiers))]
        items.append(
            ResourceItem(
                resource_id=f"RES-{i:03d}",
                label=f"Process Kit {i:03d}",
                kind=kind,
                process_area=area,
                tier=tier,
            )
        )
    return items


def build_audit_rows() -> list[AuditRow]:
    rng = Random(SEED + 4)
    endpoints = (
        "/api/dashboard/summary",
        "/api/scores/summary",
        "/api/recommendations/support-plan",
        "/api/supports/plans",
        "/api/operations/summary",
        "/api/dealerships",
    )
    statuses = ("ok", "ok", "ok", "ok", "warning", "error")
    contexts = (
        "dashboard-refresh",
        "filter-change",
        "plan-generation",
        "plan-save",
        "dealership-listing",
        "trend-review",
    )
    rows: list[AuditRow] = []
    for i in range(1, COUNTS.audit_events + 1):
        ep = endpoints[rng.randrange(len(endpoints))]
        ctx = contexts[rng.randrange(len(contexts))]
        status = statuses[rng.randrange(len(statuses))]
        duration = rng.randrange(35, 480)
        tokens = rng.randrange(0, 900)
        user = f"S-{rng.randrange(1, 21):02d}"
        rows.append(
            AuditRow(
                event_id=f"AUD-{i:04d}",
                timestamp=_offset_iso(days=i // 5, seconds=i * 137),
                endpoint=ep,
                context=ctx,
                user=user,
                provider_model="local-rules / mock-reasoner-v0",
                duration_ms=duration,
                token_estimate=tokens,
                status=status,
            )
        )
    return rows


@dataclass(frozen=True)
class SeededPlanSpec:
    plan_id: str
    dealership_id: str
    category: str
    concern_text: str
    selected_goal_id: str | None
    selected_strategy_ids: tuple[str, ...]
    created_at: str


def build_seeded_plan_specs() -> list[SeededPlanSpec]:
    rng = Random(SEED + 5)
    concerns = {
        "lead-response": "Median first response to online enquiries slipped past one hour.",
        "test-drive-conversion": "Booked test drives are attended less often than last quarter.",
        "listing-completeness": "Listings are publishing without required photos and label data.",
        "inventory-ageing": "Scheduled ageing reviews are being missed on part of the stock.",
        "price-data-freshness": "Advertised prices are not being refreshed on the agreed cadence.",
        "multi-area": "Enquiry handling, test drives, and listing quality all declined.",
    }
    specs: list[SeededPlanSpec] = []
    for i in range(1, COUNTS.seeded_plans + 1):
        category = CATEGORY_IDS[rng.randrange(len(CATEGORY_IDS))]
        dealership_num = rng.randrange(1, COUNTS.dealerships + 1)
        specs.append(
            SeededPlanSpec(
                plan_id=f"PLN-{i:04d}",
                dealership_id=f"DLR-{dealership_num:04d}",
                category=category,
                concern_text=concerns[category],
                selected_goal_id=f"GOAL-{category}-1",
                selected_strategy_ids=(f"ST-{category}-1", f"ST-{category}-2"),
                created_at=_offset_iso(days=i, seconds=i * 91),
            )
        )
    return specs
