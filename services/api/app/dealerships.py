"""Dealership query module."""

from __future__ import annotations

from .mock_data import Dealership
from .models import DealershipsResponse, DealershipSummary


def list_dealership_summaries(dealerships: list[Dealership]) -> DealershipsResponse:
    summaries = [
        DealershipSummary(
            dealership_id=dealership.dealership_id,
            display_label=dealership.display_label,
            region_id=dealership.region_id,
            segment=dealership.segment,
            process_score=dealership.process_score,
            appointment_attendance_rate=dealership.appointment_attendance_rate,
            followup_index=dealership.followup_index,
            engagement_index=dealership.engagement_index,
            flagged=dealership.flagged,
        )
        for dealership in dealerships
    ]
    return DealershipsResponse(dealerships=summaries, total=len(summaries))
