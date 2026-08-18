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

SCHOOL_IDS: tuple[str, ...] = ("SCH-001", "SCH-002", "SCH-003", "SCH-004")
GROUP_IDS: tuple[str, ...] = ("GRP-A", "GRP-B", "GRP-C")
DOMAINS: tuple[str, ...] = (
    "early-literacy",
    "reading-comprehension",
    "math-foundations",
    "math-acceleration",
    "attendance-engagement",
    "multi-domain",
)
GRADES: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)

CATEGORY_IDS: tuple[str, ...] = (
    "early-literacy",
    "attendance-support",
    "math-acceleration",
    "reading-below-grade",
    "multi-domain",
)


@dataclass(frozen=True)
class Learner:
    learner_id: str
    display_label: str
    school_id: str
    grade: int
    group: str
    proficiency_index: float
    attendance_rate: float
    behavior_index: float
    engagement_index: float
    flagged: bool


@dataclass(frozen=True)
class AssessmentRecord:
    record_id: str
    learner_id: str
    school_id: str
    grade: int
    group: str
    domain: str
    proficiency: str
    score: int
    period: str


@dataclass(frozen=True)
class BehaviorRecord:
    record_id: str
    learner_id: str
    school_id: str
    period: str
    attendance_rate: float
    behavior_incidents: int
    engagement_score: float


@dataclass(frozen=True)
class ResourceItem:
    resource_id: str
    label: str
    kind: str
    domain: str
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


def _proficiency_label(score: int) -> str:
    if score < 40:
        return "Emerging"
    if score < 60:
        return "Approaching"
    if score < 80:
        return "Proficient"
    return "Advanced"


def build_learners() -> list[Learner]:
    rng = Random(SEED)
    learners: list[Learner] = []
    for i in range(1, COUNTS.learners + 1):
        lid = f"LRN-{i:04d}"
        label = f"Learner {i:04d}"
        school = SCHOOL_IDS[rng.randrange(len(SCHOOL_IDS))]
        grade = GRADES[rng.randrange(len(GRADES))]
        group = GROUP_IDS[rng.randrange(len(GROUP_IDS))]
        proficiency = round(rng.uniform(20.0, 95.0), 1)
        attendance = round(rng.uniform(0.72, 0.99), 3)
        behavior = round(rng.uniform(30.0, 95.0), 1)
        engagement = round(rng.uniform(30.0, 95.0), 1)
        flagged = proficiency < 45 or attendance < 0.85 or behavior < 50
        learners.append(
            Learner(
                learner_id=lid,
                display_label=label,
                school_id=school,
                grade=grade,
                group=group,
                proficiency_index=proficiency,
                attendance_rate=attendance,
                behavior_index=behavior,
                engagement_index=engagement,
                flagged=flagged,
            )
        )
    return learners


def build_assessments(learners: list[Learner]) -> list[AssessmentRecord]:
    rng = Random(SEED + 1)
    records: list[AssessmentRecord] = []
    for i in range(1, COUNTS.assessments + 1):
        learner = learners[rng.randrange(len(learners))]
        domain = DOMAINS[rng.randrange(len(DOMAINS))]
        score = rng.randrange(15, 100)
        period_offset = rng.randrange(0, 6)
        period = f"2026-P{period_offset + 1:02d}"
        records.append(
            AssessmentRecord(
                record_id=f"ASM-{i:05d}",
                learner_id=learner.learner_id,
                school_id=learner.school_id,
                grade=learner.grade,
                group=learner.group,
                domain=domain,
                proficiency=_proficiency_label(score),
                score=score,
                period=period,
            )
        )
    return records


def build_behavior(learners: list[Learner]) -> list[BehaviorRecord]:
    rng = Random(SEED + 2)
    records: list[BehaviorRecord] = []
    for i in range(1, COUNTS.behavior_records + 1):
        learner = learners[rng.randrange(len(learners))]
        period_offset = rng.randrange(0, 6)
        period = f"2026-P{period_offset + 1:02d}"
        attendance = round(rng.uniform(0.70, 0.99), 3)
        incidents = rng.randrange(0, 5)
        engagement = round(rng.uniform(30.0, 95.0), 1)
        records.append(
            BehaviorRecord(
                record_id=f"BHV-{i:05d}",
                learner_id=learner.learner_id,
                school_id=learner.school_id,
                period=period,
                attendance_rate=attendance,
                behavior_incidents=incidents,
                engagement_score=engagement,
            )
        )
    return records


def build_resources() -> list[ResourceItem]:
    rng = Random(SEED + 3)
    kinds = ("guide", "practice-set", "small-group-plan", "family-message", "screening-kit")
    tiers = ("universal", "targeted", "intensive")
    items: list[ResourceItem] = []
    for i in range(1, COUNTS.resources + 1):
        domain = DOMAINS[rng.randrange(len(DOMAINS))]
        kind = kinds[rng.randrange(len(kinds))]
        tier = tiers[rng.randrange(len(tiers))]
        items.append(
            ResourceItem(
                resource_id=f"RES-{i:03d}",
                label=f"Strategy Kit {i:03d}",
                kind=kind,
                domain=domain,
                tier=tier,
            )
        )
    return items


def build_audit_rows() -> list[AuditRow]:
    rng = Random(SEED + 4)
    endpoints = (
        "/api/dashboard/summary",
        "/api/assessments/summary",
        "/api/recommendations/support-plan",
        "/api/supports/plans",
        "/api/behavior/summary",
        "/api/learners",
    )
    statuses = ("ok", "ok", "ok", "ok", "warning", "error")
    contexts = (
        "dashboard-refresh",
        "filter-change",
        "plan-generation",
        "plan-save",
        "learner-listing",
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
    learner_id: str
    category: str
    concern_text: str
    selected_smart_goal_id: str | None
    selected_strategy_ids: tuple[str, ...]
    created_at: str


def build_seeded_plan_specs() -> list[SeededPlanSpec]:
    rng = Random(SEED + 5)
    concerns = {
        "early-literacy": "Letter-sound fluency is below expected pace over the last two windows.",
        "attendance-support": "Attendance dipped below 85% across the recent period.",
        "math-acceleration": "Consistently exceeds grade-level checks; ready for enrichment.",
        "reading-below-grade": "Reading comprehension trending below grade-level over 3 windows.",
        "multi-domain": "Concerns across literacy, math, and attendance over the recent period.",
    }
    specs: list[SeededPlanSpec] = []
    for i in range(1, COUNTS.seeded_plans + 1):
        category = CATEGORY_IDS[rng.randrange(len(CATEGORY_IDS))]
        learner_num = rng.randrange(1, COUNTS.learners + 1)
        specs.append(
            SeededPlanSpec(
                plan_id=f"PLN-{i:04d}",
                learner_id=f"LRN-{learner_num:04d}",
                category=category,
                concern_text=concerns[category],
                selected_smart_goal_id=f"SG-{category}-1",
                selected_strategy_ids=(f"ST-{category}-1", f"ST-{category}-2"),
                created_at=_offset_iso(days=i, seconds=i * 91),
            )
        )
    return specs
