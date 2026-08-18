"""Shared, immutable contracts exchanged between agents.

These schemas represent a bounded context that could later be extracted
into a versioned shared library or schema registry. They intentionally
import nothing from agent implementation modules.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CONTRACT_VERSION = "1.0.0"

_STR = Field(max_length=500)
_STR_LONG = Field(max_length=2000)
_ID = Annotated[str, StringConstraints(min_length=1, max_length=60)]
_BULLET = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ResourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    detected_need: str = _STR
    evidence_bullets: list[_BULLET] = Field(default_factory=list, max_length=12)
    missing_data_flags: list[_BULLET] = Field(default_factory=list, max_length=8)
    analysis_confidence: float = Field(ge=0.0, le=1.0)


class DataAnalystOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    analysis: AnalysisSummary


class SupportRecommendationDraft(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    detected_need: str = _STR
    support_tier: str = _STR
    recommended_frequency: str = _STR
    grouping_guidance: str = _STR
    resource_ids: list[_ID] = Field(default_factory=list, max_length=8)
    rationale: str = _STR_LONG
    smart_goal_suggestions: list[_ID] = Field(default_factory=list, max_length=6)
    strategy_suggestions: list[_ID] = Field(default_factory=list, max_length=8)
    educator_next_steps: list[_BULLET] = Field(default_factory=list, max_length=8)
    progress_monitoring: list[_BULLET] = Field(default_factory=list, max_length=8)
    review_window_days: int = Field(ge=7, le=180)
    decision_rule: str = _STR
    caveats: list[_BULLET] = Field(default_factory=list, max_length=8)


class ValidatorReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    passed: bool
    issue_codes: list[_ID] = Field(default_factory=list, max_length=20)
    warning_codes: list[_ID] = Field(default_factory=list, max_length=20)
    repair_guidance: str = Field(default="", max_length=1000)


class AgentEnvelope(BaseModel):
    """Envelope used by the coordinator when carrying prior-agent output."""

    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    source_agent: str
    payload_kind: str
    payload_json: str = Field(max_length=8000)
