"""Concurrency and retention guards for the in-memory stores.

FastAPI runs sync path functions on a thread pool, so these stores are hit
concurrently. They are also process-lifetime objects, so they must not grow
without bound.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.models import SavedPlan
from app.plans_store import SavedPlansStore, _stub_recommendation
from app.telemetry import TelemetryRecorder


def _plan(plan_id: str) -> SavedPlan:
    return SavedPlan(
        plan_id=plan_id,
        learner_id="LRN-0001",
        district_id="DIST-001",
        category="early-literacy",
        concern_text="synthetic concern",
        selected_smart_goal="",
        selected_strategies=[],
        created_at="2026-01-05T09:00:00Z",
        recommendation=_stub_recommendation("early-literacy"),
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


def test_telemetry_recorder_is_bounded() -> None:
    recorder = TelemetryRecorder(None, max_events=10)
    for i in range(100):
        recorder.record("agent_call", {"district_id": f"D{i}"})
    assert len(recorder.events) == 10


def test_telemetry_clear_empties_the_buffer() -> None:
    recorder = TelemetryRecorder(None)
    recorder.record("agent_call", {"district_id": "D1"})
    assert recorder.clear() == 1
    assert recorder.events == []
