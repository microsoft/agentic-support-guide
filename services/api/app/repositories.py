"""In-memory repositories built once at startup."""

from __future__ import annotations

from dataclasses import dataclass

from .mock_data import (
    AreaScoreRecord,
    AuditRow,
    Dealership,
    OperationsRecord,
    ResourceItem,
    SeededPlanSpec,
    build_area_scores,
    build_audit_rows,
    build_dealerships,
    build_operations,
    build_resources,
    build_seeded_plan_specs,
)


@dataclass(frozen=True)
class Repositories:
    dealerships: list[Dealership]
    area_scores: list[AreaScoreRecord]
    operations: list[OperationsRecord]
    resources: list[ResourceItem]
    audit: list[AuditRow]
    seeded_plans: list[SeededPlanSpec]


def build_repositories() -> Repositories:
    dealerships = build_dealerships()
    return Repositories(
        dealerships=dealerships,
        area_scores=build_area_scores(dealerships),
        operations=build_operations(dealerships),
        resources=build_resources(),
        audit=build_audit_rows(),
        seeded_plans=build_seeded_plan_specs(),
    )
