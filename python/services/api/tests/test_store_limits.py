"""Concurrency and retention guards for the in-memory stores.

FastAPI runs sync path functions on a thread pool, so these stores are hit
concurrently. They are also process-lifetime objects, so they must not grow
without bound.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.models import SavedPlan
from app.plans_store import SavedPlansStore, _stub_recommendation


def _plan(plan_id: str) -> SavedPlan:
    return SavedPlan(
        plan_id=plan_id,
        dealership_id="DLR-0001",
        dealer_group_id="GROUP-A",
        category="lead-response",
        concern_text="synthetic concern",
        selected_goal="",
        selected_strategies=[],
        created_at="2026-01-05T09:00:00Z",
        recommendation=_stub_recommendation("lead-response"),
        human_review_state="pending_review",
    )


def test_next_plan_id_is_unique_under_concurrency() -> None:
    store = SavedPlansStore()
    with ThreadPoolExecutor(max_workers=16) as pool:
        ids = list(pool.map(lambda _: store.next_plan_id(), range(500)))
    assert len(set(ids)) == len(ids)


def test_saved_plans_store_is_bounded() -> None:
    store = SavedPlansStore(max_plans=5)
    for _ in range(50):
        store.add(_plan(store.next_plan_id()))
    assert len(store.list()) == 5
