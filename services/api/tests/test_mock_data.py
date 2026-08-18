from __future__ import annotations

import json

from app.config import COUNTS
from app.mock_data import (
    build_assessments,
    build_audit_rows,
    build_behavior,
    build_learners,
    build_resources,
    build_seeded_plan_specs,
)


def test_counts_match_spec() -> None:
    learners = build_learners()
    assert len(learners) == COUNTS.learners
    assert len(build_assessments(learners)) == COUNTS.assessments
    assert len(build_behavior(learners)) == COUNTS.behavior_records
    assert len(build_resources()) == COUNTS.resources
    assert len(build_audit_rows()) == COUNTS.audit_events
    assert len(build_seeded_plan_specs()) == COUNTS.seeded_plans


def test_two_invocations_produce_identical_json() -> None:
    def snapshot() -> str:
        learners = build_learners()
        payload = {
            "learners": [learner.__dict__ for learner in learners],
            "assessments": [record.__dict__ for record in build_assessments(learners)],
            "behavior": [record.__dict__ for record in build_behavior(learners)],
            "resources": [record.__dict__ for record in build_resources()],
            "audit": [record.__dict__ for record in build_audit_rows()],
            "seeded_plans": [record.__dict__ for record in build_seeded_plan_specs()],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    first = snapshot()
    second = snapshot()
    assert first == second, "Mock data factories must be deterministic"
    assert first.encode("utf-8") == second.encode("utf-8")


def test_learner_ids_are_synthetic() -> None:
    for learner in build_learners():
        assert learner.learner_id.startswith("LRN-")
        assert learner.display_label.startswith("Learner ")
