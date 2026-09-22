# Module 6 — Ground it with RAG (Foundry IQ)

**Time:** 35 minutes.

**Before this module:** run
[workshop/code/04_grounding_rag.py](code/04_grounding_rag.py) from earlier. It
is the same three steps in twenty lines with a dictionary instead of a search
index.

**You will have at the end:** the Module 4 agent answering from real dealer
group knowledge, with citations — and refusing to guess when the knowledge
does not cover the question.

---

## Grounding and RAG

The portal calls this feature "Knowledge" and never uses either word.

**Grounding** is the property you want: every claim in the answer is backed by
source material you supplied, and can be cited.

**RAG** — retrieval-augmented generation — is the usual way to get it:

| Step | What happens | Where |
| --- | --- | --- |
| **Retrieve** | Find passages relevant to the question | Steps 1-6: the index and the knowledge base |
| **Augment** | Put them in the prompt, fenced and labelled as data | `wrap_untrusted` in the recommender |
| **Generate** | Answer from them and cite them | The agent's `grounding_rules` |

A knowledge base is the retrieve step. The other two are yours.

Retrieval here is **not** a tool the model may choose to call. Your code
retrieves first, every time, before any model runs.

Your agent currently answers questions about things it has no source for. Its
`grounding_rules` say to prefer attached knowledge; there is no attached
knowledge, so "prefer" has nothing to prefer. An instruction cannot create a
source of facts.

## What Foundry IQ is

A managed knowledge layer over Azure AI Search **agentic retrieval** — the
retrieve step, run as a service. It breaks your question into sub-queries,
runs them, ranks results semantically, and returns passages with the metadata
needed to cite them. That is itself model-assisted work, which is why
`reasoning_effort` is a cost dial.

Two pieces, and the source must exist before the base. Both live on the same
search service.

- **Knowledge source** — where content comes from.
- **Knowledge base** — what the agent queries, built over one or more sources.

| Indexed (content is copied) | Remote (queried in place) |
| --- | --- |
| Search index, Azure blob, Azure SQL (preview), File (preview), OneLake, Indexed SharePoint | SharePoint, Fabric Data Agent, Fabric Ontology, MCP, Work IQ, Web |

Indexed sources cost storage and go stale between refreshes; remote sources
are current and cost a call per query. This module uses **Azure blob**.

**Semantic ranking** re-scores first-pass keyword results with a language
model, so a passage that answers the question outranks one that merely repeats
its words. Agentic retrieval depends on it — the `free` Search tier has no
semantic ranker, which is why the environment provisions `basic`.

**`reasoning_effort`** (`minimal`, `low`, `medium`) controls how many
sub-queries the service writes from your one question. Higher means better
recall on complex questions, more latency and more tokens. Start at `minimal`.

## 1. Generate the dealer group documents

The repo's synthetic evidence lives in
[services/api/app/evidence/fixtures.py](../services/api/app/evidence/fixtures.py),
covering six categories across three dealer groups. Each fixture citation
carries its own `dealer_group_id`, which is what step 6 turns into a
filterable index field.

`export_knowledge_docs.py` writes one markdown file per group and category:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\export_knowledge_docs.py
```

That writes 18 documents to `evals/knowledge` — three dealer groups × six
categories — and prints the upload command. The six are the five measured
process areas plus `multi-area`, which is a plan scope rather than something
that is scored. The account name is a `<storage-account>` placeholder; step 2
is where you read the real one out of Terraform.

Open one of the files before you upload it. Knowing what the agent will be
able to cite is what makes step 9's refusal legible.

## 2. Check whether you can upload, before you try

```powershell
terraform -chdir=infra output knowledge_storage_account_name
az storage account show -n <storage-account> -g <resource-group> `
  --query publicNetworkAccess -o tsv
```

**This decides your path, so check it first.**

### If it prints `Enabled`

```powershell
az storage blob upload-batch `
  --account-name <storage-account> `
  --destination group-knowledge `
  --source .\evals\knowledge `
  --auth-mode login
```

`--auth-mode login` is required. Shared keys are disabled on purpose, so
key-based commands fail with `KeyBasedAuthenticationNotPermitted`.

### If it prints `Disabled`

You cannot upload from your laptop, and neither can the Azure Portal — both
use the storage data plane. You will get:

> The request may be blocked by network rules of storage account.

This is normal in enterprise tenants: Azure Policy commonly enforces it, and
`terraform apply` cannot override a policy. Whether a Search indexer can still
reach the container depends on the account's trusted-services bypass, which
this stack does not configure explicitly — do not count on it. The workshop
does not need it either way: documents are **pushed** over the data plane
rather than crawled, so the blob source is optional.

Two ways forward:

1. **Use a File knowledge source instead of blob.** Upload the same files
   from `evals/knowledge` directly in the Foundry portal when creating the
   knowledge source. This bypasses storage networking entirely. File sources
   are in preview.
2. **Ask whoever owns the policy.** It is usually set above your
   subscription, so this is not something you can turn off yourself, and it
   is there for a reason — treat it as a conversation about the right path,
   not a blocker to route around. A VM inside a VNet with a private endpoint
   to the account is the usual approved answer.

Whichever you pick, the rest of this module is the same — the knowledge base
does not care where its source came from.

## 3. Create the knowledge source

In the portal: your project → **Build** → **Knowledge**. On a project that
has never connected a search service, this is a first-run screen rather than
a list — Foundry IQ wants an AI Search resource before it will show you
anything:

![The Knowledge (Foundry IQ) page in its first-run state, headed "Ground your
agent in enterprise knowledge", with a Foundry IQ resource picker, an Auth
Type dropdown and a Connect button.](images/module-6-knowledge-connect.png)

**Change Auth Type before you click Connect.** It defaults to `API Key`, and
that cannot work here: Terraform sets `local_authentication_enabled = false`
on the search service, so it has no keys to give you. Pick
**Project Managed Identity** instead — the same keyless path everything else
in this workshop uses.

![The Auth Type dropdown expanded, showing API Key selected and Project
Managed Identity as the second option.](images/module-6-knowledge-auth-type.png)

With both fields set, the form should look like this before you click
**Connect**:

![The Foundry IQ connect form with the resource picker set to srch-asg-abc123
and Auth Type set to Project Managed Identity, next to an enabled Connect
button.](images/module-6-knowledge-connect-configured.png)

Then create the knowledge source over your blob container.

**If you took the File path in step 2**, create a File knowledge source and
upload `evals/knowledge` directly instead — everything after this point is the
same, because the knowledge base does not care where its source came from.
The one difference to expect: step 6's script adds an `asg-ks-blob-<your-alias>`
source whenever a container name is set, which `populate-env.ps1` always
writes. Pass `--blob-container ''` to leave it out, and your base will span
the index and web sources rather than all three.

The Search service reads blob content using its own managed identity — Module
0 granted it `Storage Blob Data Reader`. No key is involved anywhere in this
path.

Name it `asg-ks-<your-alias>`.

**Use that exact prefix.** `provision_foundry_iq.py` in step 6 and the app
configuration in step 7 both assume `asg-ks-` and `asg-kb-`. Name it anything
else and the script creates a *second* set alongside yours, and the app points
at the one you did not build.

> **Why the naming matters later.** `Search Service Contributor` covers the
> entire search service, and Azure AI Search has no per-index RBAC. Here that
> is harmless — the search service is yours, not the group's, and you are the
> only person holding the role on it. But your suffix is a naming
> *convention*, not a boundary, and that distinction is the one people lose
> when they lift this pattern into an environment with several teams or
> customers on one search service. See Module 0.

## 4. Create the knowledge base

On the same **Knowledge** page, use **Create a knowledge base** over the
source you just created. Name it `asg-kb-<your-alias>` — again, the exact
prefix matters, because step 7 points the running app at that name.
Set `reasoning_effort` to `minimal`.

Wait for indexing to finish before testing. Querying an empty index returns
nothing and looks exactly like a broken configuration.

## 5. Know what a second source buys you

Dealer group documents are not the only knowledge a support team uses. Some of
it lives on public reference sites — and you want *specific* ones, not the
open web.

You are not adding this one by hand. Step 6's script creates it, over this
domain:

```
https://www.census.gov/econ/indviz/auto/main.html
```

Building it in the portal first would be work the next step throws away, and
you will see its citations when you query the base in step 9.

Two properties make this safe enough to show a customer:

- **`allowed_domains` is an allow-list, not a filter.** Nothing outside the
  listed domains is reachable, so this is not "the agent can browse the web."
- The knowledge base decides which source answers which question. Your
  dealer group documents and the public site sit side by side, and every result
  still carries a citation you can click.

> [!IMPORTANT]
> A web source needs a chat model configured on the knowledge base, because it
> summarises fetched pages. If retrieval later fails with `A model must be
> specified on the agent when using a Web knowledge source`, the model is
> usually configured correctly and the **Search service's managed identity**
> simply has not finished getting `Cognitive Services OpenAI User` on the AI
> Services account. Role assignments take a few minutes to propagate. Wait,
> then retry before changing anything — this exact message cost real debugging
> time during development, and the configuration was right the whole while.

## 6. Required — build the index your application needs

Everything so far was built for a human querying the base in the portal. Your
application needs something the portal sources do not provide: a
**filterable** `dealer_group_id`.

A filterable field is one the search engine can restrict on before ranking.
The alternative — asking the model to use only documents that mention the
right group — is an instruction, and an instruction is not a boundary.

`_build_index` in
[scripts/provision_foundry_iq.py](../scripts/provision_foundry_iq.py) declares
it:

```python
fields = [
    SimpleField(name="citation_id", type=T.String, key=True),
    # Filterable, so dealer group isolation is enforced by the engine rather
    # than by hoping the model respects an instruction.
    SimpleField(name="dealer_group_id", type=T.String, filterable=True, facetable=True),
    SimpleField(name="category", type=T.String, filterable=True, facetable=True),
    SearchableField(name="source_title", type=T.String),
    SearchableField(name="evidence_summary", type=T.String),
    ...
]
```

`SimpleField` is stored and returned but never full-text searched, and filters
only when you pass `filterable=True` — the default is `False`, so that one
argument is the isolation guarantee. `SearchableField` is tokenised and
ranked. Identifiers are the first kind, prose the second.

The retriever turns the requesting group into an OData filter,
`dealer_group_id eq '<group>'`, escaping the value before interpolating it.
The Pydantic pattern on `dealer_group_id` already forbids quotes, so the
escaping is a second layer.

Two more checks sit behind the filter: the retriever drops any returned
citation whose group does not match, and the validator re-checks every
citation independently. Three enforcement points, none of them a prompt.

### There is no portal route for this

The portal can create an index. It cannot push these documents into one with
`dealer_group_id` attached as a filterable field, which is the only part that
matters.

Dry run first — it prints the plan and creates nothing:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\provision_foundry_iq.py --suffix <your-alias> `
    --web-domains "https://www.census.gov/econ/indviz/auto/main.html"
```

Then apply the same command with `--apply`. Four steps run in a fixed order,
because a knowledge source cannot reference an index that does not exist, and
a base cannot reference a source that does not exist:

```
1/4 index          asg-evidence-<your-alias>
2/4 documents      20 pushed (no blob, no indexer)
3/4 knowledge src  asg-ks-<your-alias>
3b  web source     asg-ks-web-<your-alias> -> ...
3c  blob source    asg-ks-blob-<your-alias> -> group-knowledge
4/4 knowledge base asg-kb-<your-alias> over 3 source(s)
```

The `3c` line appears because `--blob-container` defaults to the
`KNOWLEDGE_CONTAINER` value `populate-env.ps1` wrote in Module 0. Pass
`--blob-container ""` to skip it, and the base is built over 2 sources.

Documents are **pushed** over the data plane rather than crawled by an
indexer. Blob upload is blocked by Azure Policy in many tenants, and pushing
is what lets `dealer_group_id` be a typed field rather than prose inside a
markdown blob. Step 2 is convergent: it deletes index keys no longer in the
fixtures before uploading, because `upload_documents` is an upsert and would
otherwise leave deleted evidence queryable.

> [!WARNING]
> The script rebuilds `asg-ks-<your-alias>` over the new index, adds
> `asg-ks-blob-<your-alias>` and `asg-ks-web-<your-alias>`, and replaces the
> base's source list. It updates the base you made in step 4 in place — same
> name, same object — so anything you attached to it by hand is replaced.
> What survives is the **Search connection**: the lasting output of the
> hand-work, and the reason nothing appeared on the Knowledge page until you
> connected the resource.

### Confirm the application's path works

```powershell
.\services\api\.venv\Scripts\python.exe scripts\provision_foundry_iq.py --suffix <your-alias> `
    --query "what does NADA report about new-vehicle sales"
```

```
group=GROUP-A citations=0
```

**Zero citations is the expected answer, and it is the lesson.** That command
exercises the path your *application* uses: retrieval scoped to the
search-index source and filtered to one dealer group. General market data is
not dealer group evidence, so the index correctly returns nothing — even
though the base as a whole can answer it from the web source.

The command exits 1, because for every other caller an empty result is a
failure. Do not wire this particular query into anything checking exit codes.

The base is broader than what your app asks of it. That scoping is a product
decision in `FoundryIQEvidenceRetriever`, not a limitation of the base. If you
want to see the whole base answer, query it directly with
`include_activity=True` and read which source contributed from the `activity`
list — `references[].sourceName` is empty on web results.

The Knowledge bases list now shows the base spanning all three sources. This
is also where a base created by `provision_foundry_iq.py` appears — the
script and the portal write to the same place, but nothing shows here until
the connection from step 3 exists:

![The Knowledge bases list showing asg-kb-demo spanning asg-ks-demo,
asg-ks-web-demo and asg-ks-blob-demo, with status
Active.](images/module-6-knowledge-bases.png)

## 7. Point the running app at it

Everything so far has been the portal and a script. The app you deployed in
Module 1 is still answering from in-memory fixtures.

This is the step that matters, and it is two variables:

```hcl
# infra/terraform.tfvars
api_evidence_source     = "foundry_iq"
api_knowledge_base_name = "asg-kb-<your-alias>"
```

```powershell
terraform -chdir=infra apply
```

**Then restart the API.** `terraform apply` updates the app setting, but the
worker already running keeps the value it read at startup:

```powershell
az webapp restart -g <your-resource-group> -n <your-api-app-name>
```

Measured: immediately after a successful apply, `EVIDENCE_SOURCE` in the app
settings read `foundry_iq` while `/api/health/details` still reported
`evidence_source: fixture`. Both were telling the truth about different
things. The restart is what reconciles them; allow about a minute afterwards
for the app to come back.

The app reads `EVIDENCE_SOURCE` at startup and builds either
`FixtureEvidenceRetriever` or `FoundryIQEvidenceRetriever`. Both satisfy the
same `EvidenceRetriever` protocol, so the coordinator and the three agents
are untouched by this change. That seam is the whole design:
[services/api/app/evidence/retrieval.py](../services/api/app/evidence/retrieval.py).

Verify the swap actually took effect:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\smoke_test.py --expect-evidence foundry_iq
```

Look at two things in the output:

```
evidence_source=foundry_iq knowledge_base=asg-kb-<your-alias>
evidence-retrieval   ok   provider=foundry_iq   5625ms
```

That latency is the tell. Fixtures return in 0 ms because they are a
dictionary lookup. Real retrieval costs seconds. If you see `provider=fixture`
or a 0 ms retrieval, the flip did not take. Check the app setting first:

```powershell
az webapp config appsettings list -g <your-resource-group> -n <your-api-app-name> `
  --query "[?name=='EVIDENCE_SOURCE'].value" -o tsv
```

If that already prints `foundry_iq`, the setting is fine and you are looking at
a worker that has not restarted. Restart it and check again.

**Why the app reports this at all:** the trace originally hardcoded
`provider="fixture"`, so a grounded run and a fixture run looked identical
from the outside. A demo could claim grounding it was not doing. Any trace
you build should report what actually ran, not what you intended to run.

## 8. Attach it to your agent

Open `asg-support-explainer-agent-<your-alias>` → expand **Knowledge** →
**Add** → **Connect to Foundry IQ**, pick your search connection and knowledge
base, then **Connect**.

![The agent's Knowledge section listing asg-kb-demo as an attached knowledge
base, with Save and Publish buttons active in the
header.](images/module-6-agent-knowledge-attached.png)

**Then press Save.** Connecting only stages the change in the editor — the
agent is not actually grounded until you save, which creates a new version.
Navigate away first and the browser warns you about unsaved changes; dismiss
that warning and the attachment is silently gone.

> **Keep this attachment out of the publisher's way.** Republishing the
> explainer from `agent.md` creates a new version built purely from the file,
> and the knowledge base is not in the file. Verified: a version saved with
> the base attached, then a publish produced a newer version with `Knowledge`
> empty. Module 3 publishes with `--roles-only` for exactly this reason, so
> your attachment survives — just do not run a bare `--apply` afterwards.

## 9. Re-run the Module 4 questions

Ask the in-scope question again:

> What does the dealer group say about enquiry response when first reply
> times are slower than the standard?

You should now get an answer with citations pointing at real documents.

Then the out-of-scope one:

> What is the dealer group's policy on staff parking permits?

It should now say the attached knowledge does not cover it. Compare that
directly against what Module 4 produced. Same instructions, different
behaviour — because the grounding is real.

## 10. Probe the edges

- Ask something **partially** covered. Does it answer the covered part and
  flag the rest, or blend them into one confident answer?
- Ask something where two dealer groups would disagree. The `grounding_rules` say
  to surface disagreement rather than silently picking. Does it?
- Raise `reasoning_effort` to `medium` and re-ask your hardest question.
  Measure latency. Was it worth it?

## Availability note

Foundry IQ is GA in REST API version `2026-04-01`. The portal experience is
preview and moves. If a screen does not match this module, prefer the REST
API version and check the current docs — do not assume the feature is gone.

## Check yourself

- [ ] Your knowledge source and base exist, named with your suffix.
- [ ] You added the web allow-list source by hand and saw it cited.
- [ ] `provision_foundry_iq.py --apply` built `asg-evidence-<your-alias>` with
      `dealer_group_id` filterable.
- [ ] The running app reports `provider=foundry_iq`, not `fixture`.
- [ ] The in-scope question returns citations.
- [ ] The out-of-scope question is refused rather than guessed.
- [ ] You measured the latency cost of raising `reasoning_effort`.

Next: [Module 7 — Model router](module-7-model-router.md)
