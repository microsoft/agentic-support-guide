"""Foundry IQ implementation of the EvidenceRetriever protocol.

This is what makes the running app stop serving in-memory fixtures. The
coordinator does not know or care which retriever it holds - the protocol
is the seam.

District isolation is enforced by an OData filter on a `filterable` index
field, not by asking a model nicely. A cross-district citation is
impossible here, not merely discouraged.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ..agents.shared.contracts import Citation, CitationSourceType
from .retrieval import EvidenceBundle, EvidenceRequest, EvidenceRetrievalError

# Agentic retrieval costs latency; keep it modest for an interactive demo.
DEFAULT_REASONING_EFFORT = "minimal"
MAX_RUNTIME_SECONDS = 30


class FoundryIQEvidenceRetriever:
    """Retrieves district-scoped evidence from a Foundry IQ knowledge base."""

    provider_name = "foundry_iq"

    def __init__(
        self,
        *,
        endpoint: str,
        knowledge_base: str,
        index_name: str,
        knowledge_source: str = "",
        credential_factory: Any = None,
    ) -> None:
        if not endpoint or not knowledge_base:
            raise EvidenceRetrievalError(
                "FOUNDRY_IQ_NOT_CONFIGURED",
                "AZURE_SEARCH_ENDPOINT and FOUNDRY_IQ_KNOWLEDGE_BASE must be set.",
            )
        self._endpoint = endpoint
        self._knowledge_base = knowledge_base
        self._index_name = index_name
        self.provider_model = knowledge_base
        # Provisioning names the source ks-<suffix> alongside kb-<suffix>.
        self._knowledge_source = knowledge_source or knowledge_base.replace("-kb-", "-ks-")
        self._credential_factory = credential_factory or _default_credential

    def has_district(self, district_id: str) -> bool:
        # Cheap and non-authoritative: retrieve() is what actually filters.
        return bool(district_id)

    async def retrieve(self, request: EvidenceRequest) -> EvidenceBundle:
        if not request.district_id:
            raise EvidenceRetrievalError(
                "MISSING_DISTRICT_ID",
                "Evidence request is missing a district_id.",
            )

        # The SDK client is synchronous, so keep it off the event loop.
        try:
            documents = await asyncio.to_thread(self._retrieve_sync, request)
        except EvidenceRetrievalError:
            raise
        except Exception as exc:  # noqa: BLE001 - mapped to a safe error
            raise EvidenceRetrievalError(
                "FOUNDRY_IQ_UNAVAILABLE",
                "Foundry IQ retrieval failed.",
            ) from exc

        citations = tuple(
            c
            for c in (_to_citation(doc, request.district_id) for doc in documents)
            # Defence in depth: the filter should make this impossible.
            if c is not None and c.district_id == request.district_id
        )
        return EvidenceBundle(district_id=request.district_id, citations=citations)

    def _retrieve_sync(self, request: EvidenceRequest) -> list[dict[str, Any]]:
        from azure.search.documents.knowledgebases import KnowledgeBaseRetrievalClient
        from azure.search.documents.knowledgebases.models import (
            KnowledgeBaseRetrievalRequest,
            KnowledgeRetrievalSemanticIntent,
            SearchIndexKnowledgeSourceParams,
        )

        credential = self._credential_factory()
        client = KnowledgeBaseRetrievalClient(
            endpoint=self._endpoint,
            knowledge_base_name=self._knowledge_base,
            credential=credential,
        )
        try:
            query = request.detected_need_hint or request.category
            payload = KnowledgeBaseRetrievalRequest(
                intents=[KnowledgeRetrievalSemanticIntent(search=query)],
                max_runtime_in_seconds=MAX_RUNTIME_SECONDS,
                include_activity=False,
                knowledge_source_params=[
                    SearchIndexKnowledgeSourceParams(
                        knowledge_source_name=self._knowledge_source,
                        include_references=True,
                        include_reference_source_data=True,
                        # Engine-enforced district isolation.
                        filter_add_on=f"district_id eq '{_escape_odata(request.district_id)}'",
                    )
                ],
            )
            response = client.retrieve(payload)
        finally:
            for obj in (client, credential):
                close = getattr(obj, "close", None)
                if close is not None:
                    close()

        return _flatten_references(response)


def _escape_odata(value: str) -> str:
    """Single quotes are the only OData string escape that matters here."""

    return value.replace("'", "''")


def _flatten_references(response: Any) -> list[dict[str, Any]]:
    """Pull source documents out of whatever shape the response uses."""

    out: list[dict[str, Any]] = []
    for attr in ("references", "results", "documents"):
        items = getattr(response, attr, None)
        if not items:
            continue
        for item in items:
            data = getattr(item, "source_data", None) or getattr(item, "document", None)
            if isinstance(data, dict):
                out.append(data)
        if out:
            break
    return out


def _to_citation(doc: dict[str, Any], district_id: str) -> Citation | None:
    citation_id = str(doc.get("citation_id") or "").strip()
    summary = str(doc.get("evidence_summary") or "").strip()
    # Citation enforces non-empty fields. A partial document is dropped
    # rather than allowed to raise a ValidationError mid-retrieval.
    if not citation_id or not summary:
        return None
    raw_type = str(doc.get("source_type") or "").strip()
    try:
        source_type = CitationSourceType(raw_type)
    except ValueError:
        source_type = CitationSourceType.STRUCTURED_DATA
    return Citation(
        citation_id=citation_id,
        district_id=str(doc.get("district_id") or district_id),
        source_type=source_type,
        source_title=str(doc.get("source_title") or "Untitled source"),
        section_or_page=str(doc.get("section_or_page") or "section 1"),
        evidence_summary=summary,
        source_ref=str(doc.get("source_ref") or f"foundry-iq://{citation_id}"),
        retrieved_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        confidence=0.8,
    )


def _default_credential() -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()
