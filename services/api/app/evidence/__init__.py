"""District-scoped evidence retrieval abstraction.

Production ambition: this package will resolve evidence from
per-district Microsoft Fabric workspaces/lakehouses, district-approved
PDFs, resource libraries, and policy documents (potentially via
Foundry IQ or Fabric IQ grounding).

Today: only synthetic per-district fixtures. Every retrieval call is
required to carry a `district_id`; the retriever refuses to return
citations tagged with a different district than the request.

The `EvidenceRetriever` protocol lets the coordinator swap in a real
Fabric-backed retriever later without touching agent code.
"""

from .fixtures import FixtureEvidenceRetriever, list_available_districts
from .retrieval import (
    CrossDistrictEvidenceError,
    EvidenceBundle,
    EvidenceRequest,
    EvidenceRetrievalError,
    EvidenceRetriever,
)

__all__ = [
    "CrossDistrictEvidenceError",
    "EvidenceBundle",
    "EvidenceRequest",
    "EvidenceRetrievalError",
    "EvidenceRetriever",
    "FixtureEvidenceRetriever",
    "list_available_districts",
]
