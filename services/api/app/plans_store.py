"""In-memory saved support plans, initialized from seeded specs.

Seeded plans use deterministic stub Recommendation objects so startup
never requires Azure connectivity. Real recommendations come from the
agent coordinator when the user runs the plan builder.
"""

from __future__ import annotations

import threading

from .human_review import HumanReviewState
from .mock_data import (
    AssessmentRecord,
    BehaviorRecord,
    Learner,
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

_STUB_DISTRICT = "DIST-DEMO"


def _stub_recommendation(category: str) -> Recommendation:
    return Recommendation(
        district_id=_STUB_DISTRICT,
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
        citations=[
            RecommendationCitation(
                citation_id=f"{_STUB_DISTRICT}-seed-{category}",
                district_id=_STUB_DISTRICT,
                source_type="synthetic_fixture",
                source_title="Seeded synthetic fixture",
                section_or_page="",
                evidence_summary="Seeded synthetic citation attached to a stub plan.",
                source_ref=f"fixture://{_STUB_DISTRICT.lower()}/{category}/seed",
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
                    district_id=_STUB_DISTRICT,
                    category=spec.category,
                    concern_text=spec.concern_text,
                    selected_smart_goal=spec.selected_smart_goal_id,
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
