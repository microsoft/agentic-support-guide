"""Support options catalog and rule-based recommendation engine."""

from __future__ import annotations

from .mock_data import PROCESS_AREAS, ResourceItem
from .models import (
    CategoryOption,
    GoalOption,
    Option,
    RecommendationResource,
    StrategyOption,
    SupportOptions,
)

CATEGORIES: tuple[CategoryOption, ...] = (
    CategoryOption(
        id="lead-response",
        label="Enquiry Response",
        description="Speed and completeness of the first reply to an online enquiry.",
    ),
    CategoryOption(
        id="test-drive-conversion",
        label="Test Drives",
        description="Booking, confirming, and attending scheduled test drives.",
    ),
    CategoryOption(
        id="listing-completeness",
        label="Listing Completeness",
        description="Required photos, specification, and label data present on a listing.",
    ),
    CategoryOption(
        id="inventory-ageing",
        label="Inventory Review Cadence",
        description="Whether scheduled ageing reviews are completed on time.",
    ),
    CategoryOption(
        id="price-data-freshness",
        label="Price Data Freshness",
        description="Keeping advertised price data refreshed on the agreed cadence.",
    ),
    CategoryOption(
        id="multi-area",
        label="Multi-Area Plan",
        description="Coordinated plan across enquiry handling, test drives, and listings.",
    ),
)


def _goals() -> list[GoalOption]:
    templates = {
        "lead-response": [
            "Reduce median first response to online enquiries to under 30 minutes in 6 weeks.",
            "Reply to 90% of enquiries within the same business day for 8 consecutive weeks.",
        ],
        "test-drive-conversion": [
            "Raise attended-to-booked test drive ratio by 15 percentage points in 8 weeks.",
            "Confirm every booked test drive within 24 hours for 6 consecutive weeks.",
        ],
        "listing-completeness": [
            "Publish 95% of new listings with the full required photo set within 6 weeks.",
            "Carry complete specification and label data on every new listing for 8 weeks.",
        ],
        "inventory-ageing": [
            "Complete every scheduled ageing review on time for 8 consecutive weeks.",
            "Close the review backlog to zero outstanding items within 6 weeks.",
        ],
        "price-data-freshness": [
            "Refresh advertised price data on the agreed cadence for 8 consecutive weeks.",
            "Reduce the count of stale price records to under 5% within 6 weeks.",
        ],
        "multi-area": [
            "Lift enquiry response and test drive attendance by 10% each in 8 weeks.",
            "Complete a coordinated cross-area process review with the group team.",
        ],
    }
    goals: list[GoalOption] = []
    for cat_id, options in templates.items():
        for idx, text in enumerate(options, start=1):
            goals.append(
                GoalOption(
                    id=f"GOAL-{cat_id}-{idx}",
                    label=f"Goal {idx}",
                    category_id=cat_id,
                    description=text,
                )
            )
    return goals


def _strategies() -> list[StrategyOption]:
    templates = {
        "lead-response": [
            "Named owner for the enquiry inbox during every opening hour.",
            "Standard first-reply template covering availability and next step.",
            "Daily review of enquiries still unanswered after two hours.",
        ],
        "test-drive-conversion": [
            "Confirmation message the day before every booked test drive.",
            "Prepare and stage the vehicle the evening before the appointment.",
            "Same-day follow-up on every no-show to rebook.",
        ],
        "listing-completeness": [
            "Photo and data checklist signed off before a listing publishes.",
            "Weekly audit of live listings against the required field set.",
            "Single owner for label and specification data per listing.",
        ],
        "inventory-ageing": [
            "Calendar the ageing review and protect the slot.",
            "Escalate any review more than seven days overdue.",
            "Weekly report of outstanding reviews to the general manager.",
        ],
        "price-data-freshness": [
            "Scheduled refresh window for advertised price data.",
            "Exception report listing records not refreshed on cadence.",
            "Named owner for price data per vehicle line.",
        ],
        "multi-area": [
            "Coordinated process review meeting every two weeks.",
            "Shared improvement tracker across managers and the group team.",
            "Bi-weekly group update summarising movement across areas.",
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


def build_support_options(
    dealership_labels: list[tuple[str, str]],
    *,
    dealer_groups: list[str] | None = None,
) -> SupportOptions:
    return SupportOptions(
        dealerships=[Option(id=did, label=label) for did, label in dealership_labels],
        categories=list(CATEGORIES),
        goals=_goals(),
        strategies=_strategies(),
        dealer_groups=dealer_groups or [],
    )


def resource_matches_for(
    category: str, resources: list[ResourceItem]
) -> list[RecommendationResource]:
    """Resources for a category, spread across areas for a cross-area plan.

    `multi-area` is a plan scope, not a measured area, so nothing is tagged
    with it. Matching on the name alone returned an empty list.
    """

    if category in PROCESS_AREAS:
        matches = [r for r in resources if r.process_area == category]
    else:
        first_per_area: dict[str, ResourceItem] = {}
        for item in resources:
            first_per_area.setdefault(item.process_area, item)
        matches = [first_per_area[area] for area in PROCESS_AREAS if area in first_per_area]
    return [
        RecommendationResource(id=r.resource_id, label=r.label, kind=r.kind) for r in matches[:5]
    ]
