# Module 2A — Ground it with Foundry IQ

**Time:** about 60 minutes.

**You will have at the end:** the Module 1 agent answering from real district
knowledge, with citations — and refusing to guess when the knowledge does not
cover the question.

---

## The problem you are fixing

At the end of Module 1 your agent answered a question about cafeteria peanut
allergies. Confidently. With nothing behind it.

Its `grounding_rules` said to prefer attached knowledge. There was no
attached knowledge, so "prefer" had nothing to prefer. **Instructions cannot
create grounding.** This is the most common misunderstanding about prompt
engineering and it costs teams months.

## What Foundry IQ is

A managed knowledge layer over Azure AI Search agentic retrieval. Two pieces:

- **Knowledge source** — where content comes from.
- **Knowledge base** — what the agent queries. Built over one or more sources.

Order matters: **the source must exist before the base**, and both must live
on the same search service.

### Source types

| Indexed (content is copied and indexed) | Remote (queried in place) |
| --- | --- |
| Search index | SharePoint |
| Azure blob | Fabric Data Agent |
| Azure SQL (preview) | Fabric Ontology |
| File (preview) | MCP |
| OneLake | Work IQ |
| Indexed SharePoint | Web |

This module uses **Azure blob**, because Module 0 created the container and it
is the shortest path to something real.

### Reasoning effort

Agentic retrieval takes a `reasoning_effort` of `minimal`, `low`, or
`medium`. Higher means more query decomposition — better recall on complex
questions, more latency and more tokens. Start at `minimal` and raise it only
when you can show it helps.

## 1. Generate the district documents

The repo's synthetic evidence lives in
[services/api/app/evidence/fixtures.py](../services/api/app/evidence/fixtures.py),
covering five categories across three districts. Export it to markdown files:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\export_knowledge_docs.py
```

That writes 15 documents to `evals/knowledge` — three districts × five
categories — and prints the upload command with your account name filled in.

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
  --destination district-knowledge `
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
`terraform apply` cannot override a policy. Note that the **Search indexer
can still read the container**, because the account allows trusted Azure
services — it is only your machine that is blocked.

Two ways forward:

1. **Use a File knowledge source instead of blob.** Upload the same files
   from `evals/knowledge` directly in the Foundry portal when creating the
   knowledge source. This bypasses storage networking entirely. File sources
   are in preview.
2. **Ask your subscription owner** for an exemption, or run the upload from a
   VM inside a VNet that has a private endpoint to the account.

Whichever you pick, the rest of this module is the same — the knowledge base
does not care where its source came from.

## 3. Create the knowledge source

In the portal: your project → **Knowledge** → new knowledge source → Azure
blob. Point it at your container.

The Search service reads blob content using its own managed identity — Module
0 granted it `Storage Blob Data Reader`. No key is involved anywhere in this
path.

Name it with your learner suffix: `ks-<your-alias>`.

> **Shared-environment warning.** `Search Service Contributor` covers the
> entire search service. Azure AI Search has no per-index RBAC, so your
> suffix is a naming convention, not a boundary — anyone in this workshop can
> delete your source. Fine here, not fine in production. See Module 0.

## 4. Create the knowledge base

Same screen → new knowledge base over the source you just created. Name it
`kb-<your-alias>`. Set `reasoning_effort` to `minimal`.

Wait for indexing to finish before testing. Querying an empty index returns
nothing and looks exactly like a broken configuration.

## 5. Attach it to your agent

Open `asg-support-explainer-agent-<your-alias>` → attach your knowledge base
→ publish a new version.

## 6. Re-run the Module 1 questions

Ask the in-scope question again:

> What does the district say about supporting a learner whose letter-sound
> fluency is behind pace?

You should now get an answer with citations pointing at real documents.

Then the out-of-scope one:

> What is the district's policy on cafeteria peanut allergies?

It should now say the attached knowledge does not cover it. Compare that
directly against what Module 1 produced. Same instructions, different
behaviour — because the grounding is real.

## 7. Probe the edges

- Ask something **partially** covered. Does it answer the covered part and
  flag the rest, or blend them into one confident answer?
- Ask something where two districts would disagree. The `grounding_rules` say
  to surface disagreement rather than silently picking. Does it?
- Raise `reasoning_effort` to `medium` and re-ask your hardest question.
  Measure latency. Was it worth it?

## 8. Note what is still missing

Your agent is grounded and cites sources. It still cannot:

- Guarantee that a recommendation only draws on **one** district's evidence.
- Enforce that every claim carries a citation.
- Retry when it produces something invalid.

Those are process guarantees, not knowledge problems. One agent cannot make
them, no matter how good its retrieval is. That is Module 2B.

---

## Availability note

Foundry IQ is GA in REST API version `2026-04-01`. The portal experience is
preview and moves. If a screen does not match this module, prefer the REST
API version and check the current docs — do not assume the feature is gone.

## Check yourself

- [ ] Your knowledge source and base exist, named with your suffix.
- [ ] The in-scope question returns citations.
- [ ] The out-of-scope question is refused rather than guessed.
- [ ] You measured the latency cost of raising `reasoning_effort`.

## What you should be able to explain

- Why instructions alone could not stop the model guessing.
- Why the source must exist before the base.
- Why a naming convention is not an isolation boundary.

Next: [Module 2B — From one agent to three](module-2b-orchestration.md)
