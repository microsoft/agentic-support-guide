"""Learner query module."""

from __future__ import annotations

from .mock_data import Learner
from .models import LearnersResponse, LearnerSummary


def list_learner_summaries(learners: list[Learner]) -> LearnersResponse:
    summaries = [
        LearnerSummary(
            learner_id=learner.learner_id,
            display_label=learner.display_label,
            school_id=learner.school_id,
            grade=learner.grade,
            group=learner.group,
            proficiency_index=learner.proficiency_index,
            attendance_rate=learner.attendance_rate,
            behavior_index=learner.behavior_index,
            engagement_index=learner.engagement_index,
            flagged=learner.flagged,
        )
        for learner in learners
    ]
    return LearnersResponse(learners=summaries, total=len(summaries))
