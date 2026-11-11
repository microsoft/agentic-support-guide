"""Inter-agent messages and their protocol validation.

Every hop between agents is a versioned envelope checked against a JSON
Schema in `contracts/v1/`, not a bare Python call. That is what makes one
agent replaceable without touching the next: the message is the interface.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from ..agents.shared.contracts import (
    DataAnalystOutput,
    SupportRecommendationDraft,
    ValidatorReport,
)

SCHEMA_VERSION = "1.0.0"


def envelope(
    *,
    source_agent: str,
    target_agent: str | None,
    payload: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    """Wrap a payload in the routing metadata every hop carries."""

    message: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "message_id": str(uuid.uuid4()),
        "trace_id": correlation_id,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_agent": source_agent,
        "payload": payload,
    }
    if target_agent is not None:
        message["target_agent"] = target_agent
    return message


def analyst_payload(analysis: DataAnalystOutput) -> dict[str, Any]:
    """Data Analyst -> Support Recommender."""

    return {
        "dealer_group_id": analysis.dealer_group_id,
        **analysis.analysis.model_dump(),
        "citations": [c.model_dump(mode="json") for c in analysis.citations],
        "synthetic_only": True,
    }


def recommender_payload(draft: SupportRecommendationDraft) -> dict[str, Any]:
    """Support Recommender -> Validator."""

    return {
        "dealer_group_id": draft.dealer_group_id,
        "detected_need": draft.detected_need,
        "support_tier": draft.support_tier,
        "recommended_frequency": draft.recommended_frequency,
        "grouping_guidance": draft.grouping_guidance,
        "resource_ids": list(draft.resource_ids),
        "rationale": draft.rationale,
        "goal_suggestions": list(draft.goal_suggestions),
        "strategy_suggestions": list(draft.strategy_suggestions),
        "manager_next_steps": list(draft.manager_next_steps),
        "progress_monitoring": list(draft.progress_monitoring),
        "review_window_days": draft.review_window_days,
        "decision_rule": draft.decision_rule,
        "caveats": list(draft.caveats),
        "citations": [c.model_dump(mode="json") for c in draft.citations],
        "synthetic_only": True,
    }


def validator_payload(report: ValidatorReport) -> dict[str, Any]:
    """Validator -> Coordinator."""

    return {
        "dealer_group_id": report.dealer_group_id,
        "passed": report.passed,
        "issue_codes": list(report.issue_codes),
        "warning_codes": list(report.warning_codes),
        "failed_fields": list(report.failed_fields),
        "safe_summary": report.safe_summary,
        "repair_guidance": report.repair_guidance,
        "synthetic_only": True,
    }
