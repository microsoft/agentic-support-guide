"""Validator-style completeness check for recommendation objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Recommendation

REQUIRED_FIELDS: tuple[str, ...] = (
    "detected_need",
    "evidence_summary",
    "rationale",
    "support_tier",
    "recommended_frequency",
    "grouping_guidance",
    "resource_matches",
    "educator_next_steps",
    "progress_monitoring",
    "review_window_days",
    "decision_rule",
    "caveats",
)


def validate_recommendation(rec: Recommendation) -> dict[str, bool | list[str]]:
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        value = getattr(rec, field)
        if value in (None, "", 0, []):
            missing.append(field)
    return {"ok": not missing, "missing": missing}
