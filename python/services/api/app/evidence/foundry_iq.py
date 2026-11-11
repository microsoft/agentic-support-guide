"""Foundry IQ implementation of the EvidenceRetriever protocol.

This is what makes the running app stop serving in-memory fixtures. The
coordinator does not know or care which retriever it holds - the protocol
is the seam.

Dealer group isolation is enforced by an OData filter on a `filterable` index
field, not by asking a model nicely. A cross-group citation is
impossible here, not merely discouraged.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..agents.shared.contracts import Citation, CitationSourceType
from .retrieval import EvidenceBundle, EvidenceRequest, EvidenceRetrievalError

# Agentic retrieval costs latency; keep it modest for an interactive demo.
DEFAULT_REASONING_EFFORT = "minimal"
MAX_RUNTIME_SECONDS = 30
RERANKER_THRESHOLD = 1.5


def _derive_source_name(knowledge_base: str) -> str:
    """Map a knowledge base name to its conventional knowledge source name.

    Handles `asg-kb-demo` -> `asg-ks-demo` and a portal-created `kb-demo` ->
    `ks-demo`. Anchoring on a `kb` segment rather than the substring `-kb-`
    is what makes the second case work.
    """

    return re.sub(r"(^|-)kb(-|$)", r"\1ks\2", knowledge_base)


class FoundryIQEvidenceRetriever:
    """Retrieves dealer-group-scoped evidence from a Foundry IQ knowledge base."""

    provider_name = "foundry_iq"
    # has_dealer_group cannot prove anything about a remote knowledge base without
    # a network call, so readiness must not be reported as verified.
    evidence_verifiable = False

    def __init__(
        self,
        *,
        endpoint: str,
        knowledge_base: str,
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
        self.provider_model = knowledge_base
        # Prefer an explicit source name. The fallback rewrites the LAST -kb-
        # segment so a portal-created `kb-alias` still resolves to `ks-alias`;
        # a plain .replace("-kb-", "-ks-") silently no-ops on that name and
        # leaves the retriever querying a source that does not exist.
        self._knowledge_source = knowledge_source or _derive_source_name(knowledge_base)
        self._credential_factory = credential_factory or _default_credential

    def has_dealer_group(self, dealer_group_id: str) -> bool:
        # Local check only. This retriever talks to a remote service, so it
        # cannot answer "is there evidence" without network I/O, and
        # /api/health/details is polled on every page load. Reporting True
        # here would make readiness green with a deleted knowledge base, so
        # callers must treat it as "configured", not "verified".
        return bool(dealer_group_id)

    async def retrieve(self, request: EvidenceRequest) -> EvidenceBundle:
        if not request.dealer_group_id:
            raise EvidenceRetrievalError(
                "MISSING_DEALER_GROUP_ID",
                "Evidence request is missing a dealer_group_id.",
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
            for c in (_to_citation(doc, request.dealer_group_id) for doc in documents)
            # Defence in depth: the filter should make this impossible.
            if c is not None and c.dealer_group_id == request.dealer_group_id
        )
        return EvidenceBundle(dealer_group_id=request.dealer_group_id, citations=citations)

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
                        # The demo corpus is a handful of short documents per group,
                        # so the service default threshold discards valid matches.
                        reranker_threshold=RERANKER_THRESHOLD,
                        # Engine-enforced dealer group isolation.
                        filter_add_on=(
                            f"dealer_group_id eq '{_escape_odata(request.dealer_group_id)}'"
                        ),
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


def _to_citation(doc: dict[str, Any], dealer_group_id: str) -> Citation | None:
    citation_id = str(doc.get("citation_id") or "").strip()
    summary = str(doc.get("evidence_summary") or "").strip()
    # Citation enforces non-empty fields. A partial document is dropped
    # rather than allowed to raise a ValidationError mid-retrieval.
    if not citation_id or not summary:
        return None
    # A knowledge base can hold blob and web sources alongside the index, and
    # those carry no dealer_group_id. Scoping the request to the index source
    # does NOT stop them contributing - verified against a live knowledge base.
    # Defaulting to the caller's group here would relabel unscoped content
    # as theirs, which is exactly the cross-group citation this class claims
    # to make impossible. Ownership must be proven, not assumed.
    doc_group = str(doc.get("dealer_group_id") or "").strip()
    if doc_group != dealer_group_id:
        return None
    raw_type = str(doc.get("source_type") or "").strip()
    try:
        source_type = CitationSourceType(raw_type)
    except ValueError:
        source_type = CitationSourceType.STRUCTURED_DATA
    try:
        return Citation(
            citation_id=citation_id,
            dealer_group_id=doc_group,
            source_type=source_type,
            source_title=str(doc.get("source_title") or "Untitled source"),
            section_or_page=str(doc.get("section_or_page") or "section 1"),
            evidence_summary=summary,
            source_ref=str(doc.get("source_ref") or f"foundry-iq://{citation_id}"),
            retrieved_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            confidence=0.8,
        )
    except ValidationError:
        # An over-long field is as unusable as a missing one, and letting the
        # error escape would put document text into the exception and from
        # there onto a span. Drop the document instead.
        return None


def _default_credential() -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()
