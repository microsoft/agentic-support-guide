"""Provision Foundry IQ: index, documents, knowledge source, knowledge base.

Module 6. This is the real thing, not a portal walkthrough: the index it
builds is what the running API queries once EVIDENCE_SOURCE=foundry_iq.

Documents are PUSHED straight into the index over the data plane. That is
deliberate - blob upload is blocked by Azure Policy in many tenants, and
pushing also lets us define `dealer_group_id` as a real filterable field
instead of leaving it as prose inside a markdown blob.

Order matters: index -> documents -> knowledge source -> knowledge base.

Usage:
  python scripts/provision_foundry_iq.py --suffix <you>            # dry run
  python scripts/provision_foundry_iq.py --suffix <you> --apply
  python scripts/provision_foundry_iq.py --suffix <you> --query "..."
  python scripts/provision_foundry_iq.py --suffix <you> --delete
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

ENV_FILE = REPO_ROOT / "services" / "api" / ".env"
SEMANTIC_CONFIG = "asg-semantic"


def _load_env() -> None:
    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def names(suffix: str) -> dict[str, str]:
    """Every Foundry IQ object is learner-scoped."""

    return {
        "index": f"asg-evidence-{suffix}",
        "source": f"asg-ks-{suffix}",
        "blob_source": f"asg-ks-blob-{suffix}",
        "web_source": f"asg-ks-web-{suffix}",
        "base": f"asg-kb-{suffix}",
    }


# Web IQ is an allowlist, not open browsing: the agent may only reach these
# addresses. Everything else is unreachable regardless of what it is asked.
# Addresses may be a bare domain or a specific path; include_subpages lets
# retrieval follow below that path.
# Public sources a dealer group can legitimately benchmark against. Each is
# path-scoped because `include_subpages` crawls everything beneath the address.
DEFAULT_WEB_DOMAINS = (
    "https://www.census.gov/econ/indviz/auto/main.html",
    "https://www.nada.org/nada/research-data/nada-data",
    "https://www.nada.org/nada/market-beat",
    "https://www.fueleconomy.gov/feg/label/",
)


def _aoai_endpoint() -> str:
    """Knowledge bases need the account endpoint, not the project endpoint."""

    project = os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "")
    host = project.split("/api/projects/")[0]
    return host.replace(".services.ai.azure.com", ".openai.azure.com")


def _storage_resource_id() -> str:
    """Blob sources authenticate with a managed identity, not a key."""

    import subprocess

    infra = REPO_ROOT / "infra"
    try:
        account = subprocess.run(
            ["terraform", f"-chdir={infra}", "output", "-raw", "knowledge_storage_account_id"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = (account.stdout or "").strip()
    return value if value.startswith("/subscriptions/") else ""


@contextmanager
def _index_client(endpoint: str) -> Iterator[Any]:
    """A SearchIndexClient that closes its own credential."""

    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient

    credential = DefaultAzureCredential()
    client = SearchIndexClient(endpoint=endpoint, credential=credential)
    try:
        yield client
    finally:
        client.close()
        credential.close()


@contextmanager
def _search_client(endpoint: str, index_name: str) -> Iterator[Any]:
    """A SearchClient that closes its own credential."""

    from azure.identity import DefaultAzureCredential
    from azure.search.documents import SearchClient

    credential = DefaultAzureCredential()
    client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    try:
        yield client
    finally:
        client.close()
        credential.close()


def _build_index(index_name: str) -> Any:
    from azure.search.documents.indexes.models import (
        SearchableField,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
    )
    from azure.search.documents.indexes.models import (
        SearchFieldDataType as T,
    )

    fields = [
        SimpleField(name="citation_id", type=T.String, key=True),
        # Filterable, so dealer group isolation is enforced by the engine rather
        # than by hoping the model respects an instruction.
        SimpleField(name="dealer_group_id", type=T.String, filterable=True, facetable=True),
        SimpleField(name="category", type=T.String, filterable=True, facetable=True),
        SearchableField(name="source_title", type=T.String),
        SearchableField(name="evidence_summary", type=T.String),
        SimpleField(name="source_type", type=T.String, filterable=True),
        SimpleField(name="section_or_page", type=T.String),
        SimpleField(name="source_ref", type=T.String),
    ]
    semantic = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="source_title"),
                    content_fields=[SemanticField(field_name="evidence_summary")],
                ),
            )
        ]
    )
    return SearchIndex(name=index_name, fields=fields, semantic_search=semantic)


async def _documents() -> list[dict[str, Any]]:
    """The same synthetic evidence the fixtures serve, as index documents."""

    from app.evidence import EvidenceRequest, FixtureEvidenceRetriever
    from app.evidence.fixtures import list_available_dealer_groups
    from app.mock_data import CATEGORY_IDS

    retriever = FixtureEvidenceRetriever()
    docs: list[dict[str, Any]] = []
    for group in list_available_dealer_groups():
        for category in CATEGORY_IDS:
            bundle = await retriever.retrieve(
                EvidenceRequest(dealer_group_id=group, category=category, detected_need_hint="")
            )
            for c in bundle.citations:
                docs.append(
                    {
                        "citation_id": c.citation_id,
                        "dealer_group_id": c.dealer_group_id,
                        "category": category,
                        "source_title": c.source_title,
                        "evidence_summary": c.evidence_summary,
                        "source_type": c.source_type.value,
                        "section_or_page": c.section_or_page,
                        "source_ref": c.source_ref,
                    }
                )
    return docs


@dataclass(frozen=True)
class ProvisionPlan:
    """Everything the four provisioning steps need, resolved up front.

    Built once in `_build_plan` so the dry run prints exactly what `--apply`
    would create -- there is no second code path that could drift.
    """

    endpoint: str
    suffix: str
    docs: list[dict[str, Any]]
    web_domains: tuple[str, ...]
    blob_container: str
    blob_resource_id: str
    aoai_endpoint: str
    aoai_deployment: str
    aoai_model: str = "gpt-4.1-mini"

    @property
    def names(self) -> dict[str, str]:
        return names(self.suffix)


def _push_documents(plan: ProvisionPlan) -> int:
    """Replace the index contents. Returns the number of failed operations.

    Stale keys are deleted first. `upload_documents` is an upsert, so
    re-running after the fixtures change would otherwise leave evidence for
    groups and process areas that no longer exist still queryable.
    """

    with _search_client(plan.endpoint, plan.names["index"]) as search:
        wanted = {str(d["citation_id"]) for d in plan.docs}
        existing = {
            str(r["citation_id"])
            for r in search.search(
                search_text="*", select=["citation_id"], include_total_count=False
            )
        }

        failed = 0
        stale = sorted(existing - wanted)
        if stale:
            print(f"    removing {len(stale)} stale document(s)")
            # Per-document failures are reported in the result, not raised.
            # Ignoring them would report a clean run while leaving evidence
            # for a group that no longer exists still queryable.
            deleted = search.delete_documents(documents=[{"citation_id": cid} for cid in stale])
            failed += sum(1 for r in deleted if not r.succeeded)

        uploaded = search.upload_documents(documents=plan.docs)
        return failed + sum(1 for r in uploaded if not r.succeeded)


def _index_knowledge_source(plan: ProvisionPlan) -> Any:
    from azure.search.documents.indexes.models import (
        SearchIndexFieldReference,
        SearchIndexKnowledgeSource,
        SearchIndexKnowledgeSourceParameters,
    )

    return SearchIndexKnowledgeSource(
        name=plan.names["source"],
        search_index_parameters=SearchIndexKnowledgeSourceParameters(
            search_index_name=plan.names["index"],
            # These take field-reference objects, not bare strings.
            source_data_fields=[
                SearchIndexFieldReference(name=f)
                for f in (
                    "citation_id",
                    "dealer_group_id",
                    "category",
                    "source_title",
                    "evidence_summary",
                    "source_type",
                    "section_or_page",
                    "source_ref",
                )
            ],
            search_fields=[
                SearchIndexFieldReference(name=f) for f in ("source_title", "evidence_summary")
            ],
            semantic_configuration_name=SEMANTIC_CONFIG,
        ),
    )


def _path_depth(address: str) -> int:
    """Number of non-empty path segments in a URL."""

    return len([seg for seg in urlparse(address).path.split("/") if seg])


def _web_knowledge_source(plan: ProvisionPlan) -> Any:
    from azure.search.documents.indexes.models import (
        WebKnowledgeSource,
        WebKnowledgeSourceDomain,
        WebKnowledgeSourceDomains,
        WebKnowledgeSourceParameters,
    )

    return WebKnowledgeSource(
        name=plan.names["web_source"],
        web_parameters=WebKnowledgeSourceParameters(
            domains=WebKnowledgeSourceDomains(
                allowed_domains=[
                    WebKnowledgeSourceDomain(
                        address=d,
                        # The service rejects include_subpages on an address
                        # more than two path segments deep. A deep address is
                        # already a single page, so crawl just that one.
                        include_subpages=_path_depth(d) <= 2,
                    )
                    for d in plan.web_domains
                ]
            )
        ),
    )


def _blob_knowledge_source(plan: ProvisionPlan) -> Any:
    from azure.search.documents.indexes.models import (
        AzureBlobKnowledgeSource,
        AzureBlobKnowledgeSourceParameters,
    )

    return AzureBlobKnowledgeSource(
        name=plan.names["blob_source"],
        azure_blob_parameters=AzureBlobKnowledgeSourceParameters(
            # Managed-identity form: shared keys are disabled on the account.
            connection_string=f"ResourceId={plan.blob_resource_id};",
            container_name=plan.blob_container,
        ),
    )


def _knowledge_base(plan: ProvisionPlan, references: list[Any]) -> Any:
    from azure.search.documents.indexes.models import (
        AzureOpenAIVectorizerParameters,
        KnowledgeBase,
        KnowledgeBaseAzureOpenAIModel,
    )

    # A web source makes the base do its own reasoning, which requires a
    # model. Index-only bases do not.
    models = (
        [
            KnowledgeBaseAzureOpenAIModel(
                azure_open_ai_parameters=AzureOpenAIVectorizerParameters(
                    resource_url=plan.aoai_endpoint,
                    deployment_name=plan.aoai_deployment,
                    model_name=plan.aoai_model,
                )
            )
        ]
        if plan.web_domains
        else None
    )
    return KnowledgeBase(name=plan.names["base"], knowledge_sources=references, models=models)


def _apply(plan: ProvisionPlan) -> int:
    """Index -> documents -> knowledge source(s) -> knowledge base.

    The order is not cosmetic: a knowledge source cannot reference an index
    that does not exist, and a knowledge base cannot reference a source that
    does not exist.
    """

    from azure.search.documents.indexes.models import KnowledgeSourceReference

    n = plan.names
    with _index_client(plan.endpoint) as client:
        print(f"1/4 index          {n['index']}")
        client.create_or_update_index(_build_index(n["index"]))

        print(f"2/4 documents      {len(plan.docs)} pushed (no blob, no indexer)")
        failed = _push_documents(plan)
        if failed:
            print(f"    {failed} document operation(s) failed.", file=sys.stderr)
            return 1

        print(f"3/4 knowledge src  {n['source']}")
        client.create_or_update_knowledge_source(knowledge_source=_index_knowledge_source(plan))
        references = [KnowledgeSourceReference(name=n["source"])]

        if plan.web_domains:
            print(f"3b  web source     {n['web_source']} -> {', '.join(plan.web_domains)}")
            client.create_or_update_knowledge_source(knowledge_source=_web_knowledge_source(plan))
            references.append(KnowledgeSourceReference(name=n["web_source"]))

        if plan.blob_container:
            print(f"3c  blob source    {n['blob_source']} -> {plan.blob_container}")
            client.create_or_update_knowledge_source(knowledge_source=_blob_knowledge_source(plan))
            references.append(KnowledgeSourceReference(name=n["blob_source"]))

        print(f"4/4 knowledge base {n['base']} over {len(references)} source(s)")
        client.create_or_update_knowledge_base(knowledge_base=_knowledge_base(plan, references))

    print("\nDone. Point the API at it with:")
    print("  EVIDENCE_SOURCE=foundry_iq")
    print(f"  FOUNDRY_IQ_KNOWLEDGE_BASE={n['base']}")
    print(f"  FOUNDRY_IQ_KNOWLEDGE_SOURCE={n['source']}")
    return 0


def _query(endpoint: str, suffix: str, question: str) -> int:
    from app.evidence.foundry_iq import FoundryIQEvidenceRetriever
    from app.evidence.retrieval import EvidenceRequest

    retriever = FoundryIQEvidenceRetriever(
        endpoint=endpoint,
        knowledge_base=names(suffix)["base"],
        knowledge_source=names(suffix)["source"],
    )
    bundle = asyncio.run(
        retriever.retrieve(
            EvidenceRequest(
                dealer_group_id="GROUP-A", category="lead-response", detected_need_hint=question
            )
        )
    )
    print(f"group={bundle.dealer_group_id} citations={len(bundle.citations)}")
    for c in bundle.citations:
        print(f"  [{c.citation_id}] {c.source_title}")
        print(f"      {c.evidence_summary[:110]}")
    return 0 if bundle.citations else 1


def _delete(endpoint: str, suffix: str) -> int:
    """Remove every object `--apply` can create, in reverse creation order.

    All three knowledge sources are attempted even though a given run may
    only have created one: deleting the base first leaves the others
    unreferenced and otherwise invisible until the next name collision.
    """

    from azure.core.exceptions import ResourceNotFoundError

    n = names(suffix)
    errors = 0
    with _index_client(endpoint) as client:
        targets: tuple[tuple[str, Callable[[], object]], ...] = (
            ("knowledge base", lambda: client.delete_knowledge_base(n["base"])),
            ("index knowledge source", lambda: client.delete_knowledge_source(n["source"])),
            ("web knowledge source", lambda: client.delete_knowledge_source(n["web_source"])),
            ("blob knowledge source", lambda: client.delete_knowledge_source(n["blob_source"])),
            ("index", lambda: client.delete_index(n["index"])),
        )
        for label, call in targets:
            try:
                call()
            except ResourceNotFoundError:
                print(f"  [skip] {label}: not present")
            except Exception as exc:  # noqa: BLE001 - reported, then counted
                errors += 1
                print(f"  [fail] {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
            else:
                print(f"deleted {label}")

    if errors:
        print(f"\n{errors} object(s) could not be deleted.", file=sys.stderr)
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Create index, documents, source, base."
    )
    parser.add_argument("--query", help="Retrieve against the knowledge base and print citations.")
    parser.add_argument("--delete", action="store_true", help="Remove this learner's IQ objects.")
    parser.add_argument(
        "--suffix",
        default=os.environ.get("WORKSHOP_LEARNER_SUFFIX", ""),
        help="Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
    )
    parser.add_argument(
        "--web-domains",
        default=",".join(DEFAULT_WEB_DOMAINS),
        help=(
            "Comma-separated domain allowlist for the Web IQ source. The agent "
            f"may reach nothing else. Empty disables it. Default: {','.join(DEFAULT_WEB_DOMAINS)}"
        ),
    )
    parser.add_argument(
        "--blob-container",
        default=os.environ.get("KNOWLEDGE_CONTAINER", ""),
        help="Blob container for the Azure blob source. Empty disables it.",
    )
    return parser.parse_args()


def _build_plan(endpoint: str, suffix: str, args: argparse.Namespace) -> ProvisionPlan | None:
    """Returns None when the requested plan cannot be built as asked."""

    blob_container = args.blob_container.strip()
    blob_resource_id = _storage_resource_id() if blob_container else ""
    if blob_container and not blob_resource_id:
        # Silently dropping the blob source would provision something other
        # than what was asked for, and report success for it.
        print(
            f"Blob container {blob_container!r} was requested but the storage "
            "account resource id could not be read from terraform output. Run "
            "terraform in /infra, or pass --blob-container '' to skip the blob "
            "source deliberately.",
            file=sys.stderr,
        )
        return None

    return ProvisionPlan(
        endpoint=endpoint,
        suffix=suffix,
        docs=asyncio.run(_documents()),
        web_domains=tuple(d.strip() for d in args.web_domains.split(",") if d.strip()),
        blob_container=blob_container,
        blob_resource_id=blob_resource_id,
        aoai_endpoint=_aoai_endpoint(),
        aoai_deployment=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER", "asg-chat"),
    )


def _print_plan(plan: ProvisionPlan) -> None:
    n = plan.names
    print(f"Search endpoint : {plan.endpoint}")
    for label, key in (
        ("index", "index"),
        ("index source", "source"),
        ("knowledge base", "base"),
    ):
        print(f"{label:16}: {n[key]}")
    print(f"{'documents':16}: {len(plan.docs)}")
    print(f"{'web allowlist':16}: {', '.join(plan.web_domains) or '(disabled)'}")
    print(f"{'blob container':16}: {plan.blob_container or '(disabled)'}")


def main() -> int:
    _load_env()
    args = _parse_args()

    suffix = args.suffix.strip().lower()
    if not suffix or not re.fullmatch(r"[a-z0-9-]{1,24}", suffix):
        print(
            "Pass --suffix <you> (a-z, 0-9, '-') or set WORKSHOP_LEARNER_SUFFIX.", file=sys.stderr
        )
        return 2

    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    if not endpoint:
        print(
            "AZURE_SEARCH_ENDPOINT is not set. Run .\\scripts\\populate-env.ps1.", file=sys.stderr
        )
        return 2

    if args.delete:
        return _delete(endpoint, suffix)
    if args.query:
        return _query(endpoint, suffix, args.query)

    plan = _build_plan(endpoint, suffix, args)
    if plan is None:
        return 2
    _print_plan(plan)
    if not args.apply:
        print("\nDry run. Nothing created. Re-run with --apply.")
        return 0
    return _apply(plan)


if __name__ == "__main__":
    raise SystemExit(main())
