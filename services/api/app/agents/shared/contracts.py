"""Shared, immutable contracts exchanged between agents.

These schemas represent a bounded context that could later be extracted
into a versioned shared library or schema registry. They intentionally
import nothing from agent implementation modules.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CONTRACT_VERSION = "1.0.0"

_STR = Field(max_length=500)
_STR_LONG = Field(max_length=2000)
_ID = Annotated[str, StringConstraints(min_length=1, max_length=60)]
_BULLET = Annotated[str, StringConstraints(min_length=1, max_length=300)]

# district_id has strict shape: uppercase letters, digits, and dashes.
# Kept short so it fits comfortably in trace metadata.
_DISTRICT_ID = Annotated[
    str,
    StringConstraints(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9\-]{1,31}$"),
]


class ResourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)


class CitationSourceType(str, Enum):
    """Enumerated source types allowed in a Citation.

    `synthetic_fixture` is the only source type produced by this
    prototype today; the others describe production ambitions.
    """

    STRUCTURED_DATA = "structured_data"
    DOCUMENT = "document"
    POLICY = "policy"
    RESOURCE = "resource"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class Citation(BaseModel):
    """Evidence pointer attached to a recommendation.

    A citation is district-scoped and safe to log: it never contains
    prompt text, completion text, real URLs, real document titles,
    real district names, or real IDs. `source_ref` is an opaque token
    that resolves to a district-specific evidence store; the coordinator
    validates that the `district_id` on the citation matches the request.
    """

    model_config = ConfigDict(frozen=True)
    citation_id: str = Field(min_length=1, max_length=64)
    district_id: _DISTRICT_ID
    source_type: CitationSourceType
    source_title: str = Field(min_length=1, max_length=200)
    section_or_page: str = Field(default="", max_length=80)
    evidence_summary: str = Field(min_length=1, max_length=500)
    source_ref: str = Field(min_length=1, max_length=200)
    retrieved_at: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    detected_need: str = _STR
    evidence_bullets: list[_BULLET] = Field(default_factory=list, max_length=12)
    missing_data_flags: list[_BULLET] = Field(default_factory=list, max_length=8)
    analysis_confidence: float = Field(ge=0.0, le=1.0)


class DataAnalystOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    district_id: _DISTRICT_ID
    analysis: AnalysisSummary
    citations: list[Citation] = Field(default_factory=list, max_length=12)


class SupportRecommendationDraft(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    district_id: _DISTRICT_ID
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
    citations: list[Citation] = Field(default_factory=list, max_length=12)


class ValidatorReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    district_id: _DISTRICT_ID
    passed: bool
    issue_codes: list[_ID] = Field(default_factory=list, max_length=20)
    warning_codes: list[_ID] = Field(default_factory=list, max_length=20)
    failed_fields: list[_ID] = Field(default_factory=list, max_length=20)
    safe_summary: str = Field(default="", max_length=500)
    repair_guidance: str = Field(default="", max_length=1000)


class AgentEnvelope(BaseModel):
    """Envelope used by the coordinator when carrying prior-agent output."""

    model_config = ConfigDict(frozen=True)
    contract_version: str = CONTRACT_VERSION
    source_agent: str
    payload_kind: str
    payload_json: str = Field(max_length=8000)
