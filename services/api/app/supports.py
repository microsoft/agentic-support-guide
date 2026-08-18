"""Support options catalog and rule-based recommendation engine."""

from __future__ import annotations

from .mock_data import ResourceItem
from .models import (
    CategoryOption,
    Option,
    RecommendationResource,
    SmartGoalOption,
    StrategyOption,
    SupportOptions,
)

CATEGORIES: tuple[CategoryOption, ...] = (
    CategoryOption(
        id="early-literacy",
        label="Early Literacy Support",
        description="Phonological awareness, phonics, and early decoding support.",
    ),
    CategoryOption(
        id="attendance-support",
        label="Attendance & Engagement",
        description="Attendance patterns, tardiness, and engagement recovery.",
    ),
    CategoryOption(
        id="math-acceleration",
        label="Math Acceleration",
        description="Enrichment planning for learners exceeding grade-level checks.",
    ),
    CategoryOption(
        id="reading-below-grade",
        label="Reading Below Grade Level",
        description="Targeted reading comprehension and fluency support.",
    ),
    CategoryOption(
        id="multi-domain",
        label="Multi-Domain Support",
        description="Coordinated plan across literacy, math, and attendance domains.",
    ),
)


def _smart_goals() -> list[SmartGoalOption]:
    templates = {
        "early-literacy": [
            "Increase letter-sound correspondence accuracy from baseline by 15% in 6 weeks.",
            "Improve nonsense-word fluency by 10 correct sounds per minute in 8 weeks.",
        ],
        "attendance-support": [
            "Achieve 90%+ weekly attendance for 6 consecutive weeks.",
            "Reduce unexcused tardies by 50% over the next 8 weeks.",
        ],
        "math-acceleration": [
            "Complete two enrichment units above current grade with 85%+ accuracy in 8 weeks.",
            "Present one problem-based project to peers within 6 weeks.",
        ],
        "reading-below-grade": [
            "Raise oral reading fluency by 15 words per minute in 8 weeks.",
            "Answer grade-level comprehension items at 80%+ across 4 checks.",
        ],
        "multi-domain": [
            "Meet attendance 90%+ and raise math/literacy checks by 10% each in 8 weeks.",
            "Complete a coordinated cross-domain plan review with the support team.",
        ],
    }
    goals: list[SmartGoalOption] = []
    for cat_id, options in templates.items():
        for idx, text in enumerate(options, start=1):
            goals.append(
                SmartGoalOption(
                    id=f"SG-{cat_id}-{idx}",
                    label=f"SMART goal {idx}",
                    category_id=cat_id,
                    description=text,
                )
            )
    return goals


def _strategies() -> list[StrategyOption]:
    templates = {
        "early-literacy": [
            "Daily 15-minute phonemic awareness routine in small groups.",
            "Structured decoding warm-up before core literacy block.",
            "Weekly progress check on target letter-sound patterns.",
        ],
        "attendance-support": [
            "Morning check-in with a designated staff mentor.",
            "Family communication template shared weekly.",
            "Success plan review every two weeks.",
        ],
        "math-acceleration": [
            "Curated enrichment task rotation with reflection prompts.",
            "Cross-grade problem-of-the-week collaboration.",
            "Optional independent inquiry project with a rubric.",
        ],
        "reading-below-grade": [
            "Small-group guided reading three times weekly.",
            "Comprehension routine using structured question stems.",
            "Fluency partner-reading with weekly timed check.",
        ],
        "multi-domain": [
            "Coordinated care-team meeting every two weeks.",
            "Shared learner-goal tracker across educators and mentors.",
            "Bi-weekly family update summarizing progress across domains.",
        ],
    }
    strategies: list[StrategyOption] = []
    for cat_id, items in templates.items():
        for idx, text in enumerate(items, start=1):
            strategies.append(
                StrategyOption(
                    id=f"ST-{cat_id}-{idx}",
                    label=f"Strategy {idx}",
                    category_id=cat_id,
                    description=text,
                )
            )
    return strategies


def build_support_options(learners_labels: list[tuple[str, str]]) -> SupportOptions:
    return SupportOptions(
        learners=[Option(id=lid, label=label) for lid, label in learners_labels],
        categories=list(CATEGORIES),
        smart_goals=_smart_goals(),
        strategies=_strategies(),
    )


def resource_matches_for(
    category: str, resources: list[ResourceItem]
) -> list[RecommendationResource]:
    domain_map = {
        "early-literacy": "early-literacy",
        "attendance-support": "attendance-engagement",
        "math-acceleration": "math-acceleration",
        "reading-below-grade": "reading-comprehension",
        "multi-domain": "multi-domain",
    }
    target_domain = domain_map.get(category, "multi-domain")
    matches = [
        RecommendationResource(id=r.resource_id, label=r.label, kind=r.kind)
        for r in resources
        if r.domain == target_domain
    ]
    return matches[:5]
