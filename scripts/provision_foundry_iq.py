"""Provision Foundry IQ: index, documents, knowledge source, knowledge base.

Module 3. This is the real thing, not a portal walkthrough: the index it
builds is what the running API queries once EVIDENCE_SOURCE=foundry_iq.

Documents are PUSHED straight into the index over the data plane. That is
deliberate - blob upload is blocked by Azure Policy in many tenants, and
pushing also lets us define `district_id` as a real filterable field
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
from pathlib import Path
from typing import Any

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
DEFAULT_WEB_DOMAINS = ("https://dyslexiaida.org/additional-resources/",)


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


def _index_client(endpoint: str) -> Any:
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient

    return SearchIndexClient(endpoint=endpoint, credential=DefaultAzureCredential())


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
        # Filterable, so district isolation is enforced by the engine rather
        # than by hoping the model respects an instruction.
        SimpleField(name="district_id", type=T.String, filterable=True, facetable=True),
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
    from app.evidence.fixtures import list_available_districts
    from app.mock_data import CATEGORY_IDS

    retriever = FixtureEvidenceRetriever()
    docs: list[dict[str, Any]] = []
    for district in list_available_districts():
        for category in CATEGORY_IDS:
            bundle = await retriever.retrieve(
                EvidenceRequest(district_id=district, category=category, detected_need_hint="")
            )
            for c in bundle.citations:
                docs.append(
                    {
                        "citation_id": c.citation_id,
                        "district_id": c.district_id,
                        "category": category,
                        "source_title": c.source_title,
                        "evidence_summary": c.evidence_summary,
                        "source_type": c.source_type.value,
                        "section_or_page": c.section_or_page,
                        "source_ref": c.source_ref,
                    }
                )
    return docs


def _apply(
    endpoint: str,
    suffix: str,
    docs: list[dict[str, Any]],
    *,
    web_domains: tuple[str, ...] = (),
    blob_container: str = "",
    blob_resource_id: str = "",
    aoai_endpoint: str = "",
    aoai_deployment: str = "",
    aoai_model: str = "gpt-4.1-mini",
) -> int:
    from azure.identity import DefaultAzureCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes.models import (
        AzureBlobKnowledgeSource,
        AzureBlobKnowledgeSourceParameters,
        AzureOpenAIVectorizerParameters,
        KnowledgeBase,
        KnowledgeBaseAzureOpenAIModel,
        KnowledgeSourceReference,
        SearchIndexFieldReference,
        SearchIndexKnowledgeSource,
        SearchIndexKnowledgeSourceParameters,
        WebKnowledgeSource,
        WebKnowledgeSourceDomain,
        WebKnowledgeSourceDomains,
        WebKnowledgeSourceParameters,
    )

    n = names(suffix)
    client = _index_client(endpoint)

    print(f"1/4 index          {n['index']}")
    client.create_or_update_index(_build_index(n["index"]))

    print(f"2/4 documents      {len(docs)} pushed (no blob, no indexer)")
    search = SearchClient(
        endpoint=endpoint, index_name=n["index"], credential=DefaultAzureCredential()
    )
    result = search.upload_documents(documents=docs)
    failed = [r for r in result if not r.succeeded]
    if failed:
        print(f"    {len(failed)} document(s) failed to upload.", file=sys.stderr)
        return 1

    # The source must exist before the base that references it.
    print(f"3/4 knowledge src  {n['source']}")
    source = SearchIndexKnowledgeSource(
        name=n["source"],
        search_index_parameters=SearchIndexKnowledgeSourceParameters(
            search_index_name=n["index"],
            # These take field-reference objects, not bare strings.
            source_data_fields=[
                SearchIndexFieldReference(name=f)
                for f in (
                    "citation_id",
                    "district_id",
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
    client.create_or_update_knowledge_source(knowledge_source=source)

    references = [KnowledgeSourceReference(name=n["source"])]

    if web_domains:
        print(f"3b  web source     {n['web_source']} -> {', '.join(web_domains)}")
        web = WebKnowledgeSource(
            name=n["web_source"],
            web_parameters=WebKnowledgeSourceParameters(
                domains=WebKnowledgeSourceDomains(
                    allowed_domains=[
                        WebKnowledgeSourceDomain(address=d, include_subpages=True)
                        for d in web_domains
                    ]
                )
            ),
        )
        client.create_or_update_knowledge_source(knowledge_source=web)
        references.append(KnowledgeSourceReference(name=n["web_source"]))

    if blob_container:
        print(f"3c  blob source    {n['blob_source']} -> {blob_container}")
        blob = AzureBlobKnowledgeSource(
            name=n["blob_source"],
            azure_blob_parameters=AzureBlobKnowledgeSourceParameters(
                # Managed-identity form: shared keys are disabled on the account.
                connection_string=f"ResourceId={blob_resource_id};",
                container_name=blob_container,
            ),
        )
        client.create_or_update_knowledge_source(knowledge_source=blob)
        references.append(KnowledgeSourceReference(name=n["blob_source"]))

    print(f"4/4 knowledge base {n['base']} over {len(references)} source(s)")
    models = None
    if web_domains:
        # A web source makes the base do its own reasoning, which requires a
        # model. Index-only bases do not.
        models = [
            KnowledgeBaseAzureOpenAIModel(
                azure_open_ai_parameters=AzureOpenAIVectorizerParameters(
                    resource_url=aoai_endpoint,
                    deployment_name=aoai_deployment,
                    model_name=aoai_model,
                )
            )
        ]
    base = KnowledgeBase(name=n["base"], knowledge_sources=references, models=models)
    client.create_or_update_knowledge_base(knowledge_base=base)

    print("\nDone. Point the API at it with:")
    print("  EVIDENCE_SOURCE=foundry_iq")
    print(f"  FOUNDRY_IQ_KNOWLEDGE_BASE={n['base']}")
    print(f"  FOUNDRY_IQ_INDEX={n['index']}")
    return 0


def _query(endpoint: str, suffix: str, question: str) -> int:
    from app.evidence.foundry_iq import FoundryIQEvidenceRetriever
    from app.evidence.retrieval import EvidenceRequest

    retriever = FoundryIQEvidenceRetriever(
        endpoint=endpoint,
        knowledge_base=names(suffix)["base"],
        index_name=names(suffix)["index"],
    )
    bundle = asyncio.run(
        retriever.retrieve(
            EvidenceRequest(
                district_id="DIST-A", category="early-literacy", detected_need_hint=question
            )
        )
    )
    print(f"district={bundle.district_id} citations={len(bundle.citations)}")
    for c in bundle.citations:
        print(f"  [{c.citation_id}] {c.source_title}")
        print(f"      {c.evidence_summary[:110]}")
    return 0 if bundle.citations else 1


def _delete(endpoint: str, suffix: str) -> int:
    n = names(suffix)
    client = _index_client(endpoint)
    # Reverse creation order: the base references the source.
    for label, call in (
        ("knowledge base", lambda: client.delete_knowledge_base(n["base"])),
        ("knowledge source", lambda: client.delete_knowledge_source(n["source"])),
        ("index", lambda: client.delete_index(n["index"])),
    ):
        try:
            call()
            print(f"deleted {label}")
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            print(f"  [skip] {label}: {type(exc).__name__}")
    return 0


def main() -> int:
    _load_env()
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
    args = parser.parse_args()

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

    docs = asyncio.run(_documents())
    n = names(suffix)
    web_domains = tuple(d.strip() for d in args.web_domains.split(",") if d.strip())
    blob_container = args.blob_container.strip()
    blob_resource_id = _storage_resource_id() if blob_container else ""
    if blob_container and not blob_resource_id:
        print(
            "Blob source requested but the storage account resource id could not "
            "be read from terraform output; skipping the blob source.",
            file=sys.stderr,
        )
        blob_container = ""

    print(f"Search endpoint : {endpoint}")
    for label, key in (
        ("index", "index"),
        ("index source", "source"),
        ("knowledge base", "base"),
    ):
        print(f"{label:16}: {n[key]}")
    print(f"{'documents':16}: {len(docs)}")
    print(f"{'web allowlist':16}: {', '.join(web_domains) or '(disabled)'}")
    print(f"{'blob container':16}: {blob_container or '(disabled)'}")
    if not args.apply:
        print("\nDry run. Nothing created. Re-run with --apply.")
        return 0
    return _apply(
        endpoint,
        suffix,
        docs,
        web_domains=web_domains,
        blob_container=blob_container,
        blob_resource_id=blob_resource_id,
        aoai_endpoint=_aoai_endpoint(),
        aoai_deployment=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER", "asg-chat"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
