"""In-memory saved support plans, initialized from seeded specs.

Seeded plans use deterministic stub Recommendation objects so startup
never requires Azure connectivity. Real recommendations come from the
agent coordinator when the user runs the plan builder.
"""

from __future__ import annotations

import threading

from .human_review import HumanReviewState
from .mock_data import (
    AreaScoreRecord,
    Dealership,
    OperationsRecord,
    ResourceItem,
    SeededPlanSpec,
)
from .models import (
    Recommendation,
    RecommendationCitation,
    RecommendationResource,
    SavedPlan,
)

_STUB_CAVEATS = (
    "Illustrative synthetic output only; not a real benchmark.",
    "Human review is required before any decision or communication.",
)

_STUB_DEALER_GROUP = "GROUP-DEMO"


def _stub_recommendation(category: str) -> Recommendation:
    return Recommendation(
        dealer_group_id=_STUB_DEALER_GROUP,
        detected_need=f"Seeded example for category '{category}'.",
        evidence_summary=[
            "Synthetic seeded evidence line 1.",
            "Synthetic seeded evidence line 2.",
        ],
        rationale=(
            "Seeded example recommendation. Regenerate via the plan builder "
            "for a live agent-produced version."
        ),
        support_tier="Focused",
        recommended_frequency="weekly review, 20-25 min",
        grouping_guidance="single dealership with group oversight",
        resource_matches=[
            RecommendationResource(id="RES-001", label="Seeded Kit 001", kind="playbook"),
        ],
        manager_next_steps=["Confirm the review slot.", "Brief the sales manager."],
        progress_monitoring=["Weekly check on the agreed measure."],
        review_window_days=28,
        decision_rule="Seeded stub - see the coordinator for live decision rules.",
        caveats=list(_STUB_CAVEATS),
        goal_suggestions=[f"GOAL-{category}-1"],
        strategy_suggestions=[f"ST-{category}-1"],
        citations=[
            RecommendationCitation(
                citation_id=f"{_STUB_DEALER_GROUP}-seed-{category}",
                dealer_group_id=_STUB_DEALER_GROUP,
                source_type="synthetic_fixture",
                source_title="Seeded synthetic fixture",
                section_or_page="",
                evidence_summary="Seeded synthetic citation attached to a stub plan.",
                source_ref=f"fixture://{_STUB_DEALER_GROUP.lower()}/{category}/seed",
                retrieved_at="2026-01-05T09:00:00Z",
                confidence=0.7,
            )
        ],
        completeness={"ok": True, "missing": []},
        human_review_state=HumanReviewState.PENDING_REVIEW.value,
        generated_by="Seeded synthetic stub. Not a real agent output.",
    )


class SavedPlansStore:
    """Process-local plan store. Resets on server restart.

    FastAPI runs sync path functions on a thread pool, so every mutation is
    guarded. Retention is capped so a long-lived process cannot grow without
    bound from repeated saves.
    """

    def __init__(self, max_plans: int = 500) -> None:
        self._plans: list[SavedPlan] = []
        self._counter = 0
        self._max = max_plans
        self._lock = threading.Lock()

    def seed(
        self,
        specs: list[SeededPlanSpec],
        dealerships: list[Dealership],
        area_scores: list[AreaScoreRecord],
        operations: list[OperationsRecord],
        resources: list[ResourceItem],
    ) -> None:
        del area_scores, operations, resources
        dealerships_by_id = {d.dealership_id: d for d in dealerships}
        # Every other mutator takes the lock. `demo/reset` calls this while
        # other requests are reading and appending, so without it the list and
        # the id counter can diverge.
        with self._lock:
            for spec in specs:
                if spec.dealership_id not in dealerships_by_id:
                    continue
                self._plans.append(
                    SavedPlan(
                        plan_id=spec.plan_id,
                        dealership_id=spec.dealership_id,
                        dealer_group_id=_STUB_DEALER_GROUP,
                        category=spec.category,
                        concern_text=spec.concern_text,
                        selected_goal=spec.selected_goal_id,
                        selected_strategies=list(spec.selected_strategy_ids),
                        created_at=spec.created_at,
                        recommendation=_stub_recommendation(spec.category),
                        human_review_state=HumanReviewState.PENDING_REVIEW.value,
                    )
                )
                self._counter += 1

    def list(self) -> list[SavedPlan]:
        with self._lock:
            return list(self._plans)

    def get(self, plan_id: str) -> SavedPlan | None:
        with self._lock:
            for plan in self._plans:
                if plan.plan_id == plan_id:
                    return plan
            return None

    def add(self, plan: SavedPlan) -> SavedPlan:
        with self._lock:
            self._plans.append(plan)
            if len(self._plans) > self._max:
                del self._plans[: len(self._plans) - self._max]
            return plan

    def replace(self, plan: SavedPlan) -> SavedPlan:
        with self._lock:
            for i, existing in enumerate(self._plans):
                if existing.plan_id == plan.plan_id:
                    self._plans[i] = plan
                    return plan
            raise KeyError(plan.plan_id)

    def next_plan_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"PLN-U{self._counter:04d}"

    def clear(self) -> int:
        with self._lock:
            removed = len(self._plans)
            self._plans = []
            self._counter = 0
            return removed
