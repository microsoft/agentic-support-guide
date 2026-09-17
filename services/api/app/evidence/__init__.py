"""Dealer-group-scoped evidence retrieval abstraction.

Production ambition: this package will resolve evidence from per-group
Microsoft Fabric workspaces/lakehouses, group-approved documents,
resource libraries, and policy documents (potentially via Foundry IQ or
Fabric IQ grounding).

Today: only synthetic per-group fixtures. Every retrieval call is
required to carry a `dealer_group_id`; the retriever refuses to return
citations tagged with a different group than the request.

The `EvidenceRetriever` protocol lets the coordinator swap in a real
Fabric-backed retriever later without touching agent code.
"""

from .fixtures import FixtureEvidenceRetriever, list_available_dealer_groups
from .retrieval import (
    CrossDealerGroupEvidenceError,
    EvidenceBundle,
    EvidenceRequest,
    EvidenceRetrievalError,
    EvidenceRetriever,
)

__all__ = [
    "CrossDealerGroupEvidenceError",
    "EvidenceBundle",
    "EvidenceRequest",
    "EvidenceRetrievalError",
    "EvidenceRetriever",
    "FixtureEvidenceRetriever",
    "list_available_dealer_groups",
]
