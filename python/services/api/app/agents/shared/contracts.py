"""Shared, immutable contracts exchanged between agents.

These schemas represent a bounded context that could later be extracted
into a versioned shared library or schema registry. They intentionally
import nothing from agent implementation modules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"

_STR_LONG = Field(max_length=2000)
_ID = Annotated[str, StringConstraints(min_length=1, max_length=60)]
_BULLET = Annotated[str, StringConstraints(min_length=1, max_length=300)]

# Citation IDs come from the evidence store, not from the model, and run
# longer than the resource IDs `_ID` covers.
_CITATION_ID = Annotated[str, StringConstraints(min_length=1, max_length=64)]

# These mirror the caps on `Recommendation` in app/models.py. They must not be
# looser: a draft the validator approves but the response model rejects fails
# after the point where a typed refusal can still be returned.
_NEED = Field(max_length=300)
_TIER = Field(max_length=60)
_FREQUENCY = Field(max_length=120)
_GROUPING = Field(max_length=200)
_DECISION_RULE = Field(max_length=300)

# Same shape the JSON Schemas enforce for issue codes.
_CODE = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{3,59}$")]

# dealer_group_id has strict shape: uppercase letters, digits, and dashes.
# Kept short so it fits comfortably in trace metadata.
_DEALER_GROUP_ID = Annotated[
    str,
    StringConstraints(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9\-]{1,31}$"),
]


class ResourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)


class CitationSourceType(StrEnum):
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

    A citation is dealer-group-scoped and safe to log: it never contains
    prompt text, completion text, real URLs, real document titles,
    real group names, or real IDs. `source_ref` is an opaque token
    that resolves to a group-specific evidence store; the coordinator
    validates that the `dealer_group_id` on the citation matches the request.
    """

    model_config = ConfigDict(frozen=True)
    citation_id: _CITATION_ID
    dealer_group_id: _DEALER_GROUP_ID
    source_type: CitationSourceType
    source_title: str = Field(min_length=1, max_length=200)
    section_or_page: str = Field(default="", max_length=80)
    evidence_summary: str = Field(min_length=1, max_length=500)
    source_ref: str = Field(min_length=1, max_length=200)
    retrieved_at: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    detected_need: str = _NEED
    evidence_bullets: list[_BULLET] = Field(default_factory=list, max_length=12)
    missing_data_flags: list[_BULLET] = Field(default_factory=list, max_length=8)
    analysis_confidence: float = Field(ge=0.0, le=1.0)


class DataAnalystOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    dealer_group_id: _DEALER_GROUP_ID
    analysis: AnalysisSummary
    citations: list[Citation] = Field(default_factory=list, max_length=12)


class SupportRecommendationDraft(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    dealer_group_id: _DEALER_GROUP_ID
    detected_need: str = _NEED
    support_tier: str = _TIER
    recommended_frequency: str = _FREQUENCY
    grouping_guidance: str = _GROUPING
    resource_ids: list[_ID] = Field(default_factory=list, max_length=8)
    rationale: str = _STR_LONG
    goal_suggestions: list[_ID] = Field(default_factory=list, max_length=6)
    strategy_suggestions: list[_ID] = Field(default_factory=list, max_length=8)
    manager_next_steps: list[_BULLET] = Field(default_factory=list, max_length=8)
    progress_monitoring: list[_BULLET] = Field(default_factory=list, max_length=8)
    review_window_days: int = Field(ge=7, le=180)
    decision_rule: str = _DECISION_RULE
    caveats: list[_BULLET] = Field(default_factory=list, max_length=8)
    citations: list[Citation] = Field(default_factory=list, max_length=12)


class ValidatorReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    dealer_group_id: _DEALER_GROUP_ID
    passed: bool
    issue_codes: list[_CODE] = Field(default_factory=list, max_length=20)
    warning_codes: list[_CODE] = Field(default_factory=list, max_length=20)
    failed_fields: list[_ID] = Field(default_factory=list, max_length=20)
    safe_summary: str = Field(default="", max_length=500)
    repair_guidance: str = Field(default="", max_length=1000)


# --- Model-facing output shapes -------------------------------------------
# These are what the LLM is asked to emit, and what `response_format` targets.
# They deliberately omit fields the coordinator injects from trusted context
# (dealer_group_id above all), which the model has no way to know.


class DataAnalystModelOutput(BaseModel):
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    analysis: AnalysisSummary


class SupportRecommendationModelOutput(BaseModel):
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    detected_need: str = _NEED
    support_tier: str = _TIER
    recommended_frequency: str = _FREQUENCY
    grouping_guidance: str = _GROUPING
    resource_ids: list[_ID] = Field(default_factory=list, max_length=8)
    rationale: str = _STR_LONG
    goal_suggestions: list[_ID] = Field(default_factory=list, max_length=6)
    strategy_suggestions: list[_ID] = Field(default_factory=list, max_length=8)
    manager_next_steps: list[_BULLET] = Field(default_factory=list, max_length=8)
    progress_monitoring: list[_BULLET] = Field(default_factory=list, max_length=8)
    review_window_days: int = Field(ge=7, le=180)
    decision_rule: str = _DECISION_RULE
    caveats: list[_BULLET] = Field(default_factory=list, max_length=8)
    # IDs only. The wrapper resolves them against the group-scoped evidence
    # bundle, so the model cannot fabricate citation text.
    cited_ids: list[_CITATION_ID] = Field(default_factory=list, max_length=12)


class ValidatorCritiqueModelOutput(BaseModel):
    """Advisory-only critique. The deterministic checks own pass/fail.

    `warning_codes` is deliberately untyped free text: this is raw model
    output, and `enforce_code` drops anything off-format afterwards. Making
    the field strict turns one malformed advisory code into a failed run.
    """

    warning_codes: list[str] = Field(default_factory=list, max_length=20)
    repair_guidance: str = Field(default="", max_length=1000)


class AgentEnvelope(BaseModel):
    """Envelope used by the coordinator when carrying prior-agent output."""

    model_config = ConfigDict(frozen=True)
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    source_agent: str
    payload_kind: str
    payload_json: str = Field(max_length=8000)
