"""What the validator is given to check against.

In its own module so `checks.py` and `agent.py` can both import it without a
cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..shared.contracts import DataAnalystOutput, SupportRecommendationDraft


@dataclass(frozen=True)
class ValidatorContext:
    dealer_group_id: str
    allowed_resource_ids: tuple[str, ...]
    allowed_goal_ids: tuple[str, ...]
    allowed_strategy_ids: tuple[str, ...]
    allowed_citation_ids: tuple[str, ...]
    required_contract_version: str


@dataclass(frozen=True)
class ValidatorInput:
    analysis: DataAnalystOutput
    draft: SupportRecommendationDraft
    context: ValidatorContext
