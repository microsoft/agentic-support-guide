"""In-memory repositories built once at startup."""

from __future__ import annotations

from dataclasses import dataclass

from .mock_data import (
    AssessmentRecord,
    AuditRow,
    BehaviorRecord,
    Learner,
    ResourceItem,
    SeededPlanSpec,
    build_assessments,
    build_audit_rows,
    build_behavior,
    build_learners,
    build_resources,
    build_seeded_plan_specs,
)


@dataclass(frozen=True)
class Repositories:
    learners: list[Learner]
    assessments: list[AssessmentRecord]
    behavior: list[BehaviorRecord]
    resources: list[ResourceItem]
    audit: list[AuditRow]
    seeded_plans: list[SeededPlanSpec]


def build_repositories() -> Repositories:
    learners = build_learners()
    return Repositories(
        learners=learners,
        assessments=build_assessments(learners),
        behavior=build_behavior(learners),
        resources=build_resources(),
        audit=build_audit_rows(),
        seeded_plans=build_seeded_plan_specs(),
    )
