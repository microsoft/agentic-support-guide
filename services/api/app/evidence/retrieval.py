"""Retrieval interface + errors, kept free of concrete backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..agents.shared.contracts import Citation


class EvidenceRetrievalError(Exception):
    """Base class for retrieval failures. Only carries safe codes."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(f"{code}: {safe_message}")
        self.code = code
        self.safe_message = safe_message


class CrossDistrictEvidenceError(EvidenceRetrievalError):
    """Retriever returned a citation whose district does not match request."""


@dataclass(frozen=True)
class EvidenceRequest:
    """District-scoped retrieval request.

    `district_id` is mandatory. A retriever MUST NOT return citations
    from other districts even if the caller misroutes the request.
    """

    district_id: str
    category: str
    detected_need_hint: str
    max_items: int = 6


@dataclass(frozen=True)
class EvidenceBundle:
    """Return type for a retrieval call. `citations` is district-scoped."""

    district_id: str
    citations: tuple[Citation, ...]

    def is_empty(self) -> bool:
        return len(self.citations) == 0


class EvidenceRetriever(Protocol):
    """Stable interface used by the coordinator.

    `retrieve` is async because real implementations do network I/O. The
    fixture retriever is in-memory and returns immediately, but it still
    implements the async signature so a Foundry IQ or Fabric retriever can
    be swapped in without touching the coordinator or the agents.
    """

    #: Shown in the agent trace so a reader can tell grounded answers from
    #: fixture answers. Hardcoding this made the trace claim "fixture" even
    #: when Foundry IQ served the evidence.
    provider_name: str

    #: What actually produced the evidence: "synthetic" for fixtures, the
    #: knowledge base name for Foundry IQ.
    provider_model: str

    async def retrieve(self, request: EvidenceRequest) -> EvidenceBundle:
        """Return a district-scoped evidence bundle.

        Raises `EvidenceRetrievalError` on failure. Must not return
        citations tagged with a different district than the request.
        """
        ...

    def has_district(self, district_id: str) -> bool:
        """Return True if the retriever has any evidence for this district."""
        ...
