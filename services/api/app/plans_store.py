"""In-memory saved support plans, initialized from seeded specs.

Seeded plans use deterministic stub Recommendation objects so startup
never requires Azure connectivity. Real recommendations come from the
agent coordinator when the user runs the plan builder.
"""

from __future__ import annotations

from .mock_data import (
    AssessmentRecord,
    BehaviorRecord,
    Learner,
    ResourceItem,
    SeededPlanSpec,
)
from .models import Recommendation, RecommendationResource, SavedPlan

_STUB_CAVEATS = (
    "Illustrative synthetic output only; not a real benchmark.",
    "Human review is required before any decision or communication.",
)


def _stub_recommendation(category: str) -> Recommendation:
    return Recommendation(
        detected_need=f"Seeded example for category '{category}'.",
        evidence_summary=[
            "Synthetic seeded evidence line 1.",
            "Synthetic seeded evidence line 2.",
        ],
        rationale=(
            "Seeded example recommendation. Regenerate via the plan builder "
            "for a live agent-produced version."
        ),
        support_tier="Targeted support (Tier 2)",
        recommended_frequency="3x weekly, 20-25 min",
        grouping_guidance="small group of 3-5",
        resource_matches=[
            RecommendationResource(id="RES-001", label="Seeded Kit 001", kind="guide"),
        ],
        educator_next_steps=["Coordinate scheduling.", "Communicate with the support team."],
        progress_monitoring=["Weekly 3-minute probe."],
        review_window_days=28,
        decision_rule="Seeded stub - see the coordinator for live decision rules.",
        caveats=list(_STUB_CAVEATS),
        smart_goal_suggestions=[f"SG-{category}-1"],
        strategy_suggestions=[f"ST-{category}-1"],
        completeness={"ok": True, "missing": []},
        generated_by="Seeded synthetic stub. Not a real agent output.",
    )


class SavedPlansStore:
    """Process-local plan store. Resets on server restart."""

    def __init__(self) -> None:
        self._plans: list[SavedPlan] = []
        self._counter = 0

    def seed(
        self,
        specs: list[SeededPlanSpec],
        learners: list[Learner],
        assessments: list[AssessmentRecord],
        behavior: list[BehaviorRecord],
        resources: list[ResourceItem],
    ) -> None:
        del assessments, behavior, resources
        learners_by_id = {learner.learner_id: learner for learner in learners}
        for spec in specs:
            if spec.learner_id not in learners_by_id:
                continue
            self._plans.append(
                SavedPlan(
                    plan_id=spec.plan_id,
                    learner_id=spec.learner_id,
                    category=spec.category,
                    concern_text=spec.concern_text,
                    selected_smart_goal=spec.selected_smart_goal_id,
                    selected_strategies=list(spec.selected_strategy_ids),
                    created_at=spec.created_at,
                    recommendation=_stub_recommendation(spec.category),
                )
            )
            self._counter += 1

    def list(self) -> list[SavedPlan]:
        return list(self._plans)

    def add(self, plan: SavedPlan) -> SavedPlan:
        self._plans.append(plan)
        return plan

    def next_plan_id(self) -> str:
        self._counter += 1
        return f"PLN-U{self._counter:04d}"

    def clear(self) -> int:
        removed = len(self._plans)
        self._plans = []
        self._counter = 0
        return removed
