# Plan this workshop for a group

For whoever sizes and pays for the environment. Attendees do not need this
page — their requirements are in the
[workshop prerequisites](README.md#prerequisites).

Each attendee deploys a complete stack of their own: resource group, Foundry
project, three model deployments, search service, storage and two App
Services. **The subscription is the only thing shared**, which means pooled
model quota and globally unique resource names.

Every table below is **per attendee**. Multiply by your headcount.

## 1. Resource providers

Registered **once per subscription**, not per attendee. An unregistered
provider fails several minutes into `terraform apply`, not at plan time.

```powershell
@(
    "Microsoft.CognitiveServices", "Microsoft.Search", "Microsoft.Storage",
    "Microsoft.Web", "Microsoft.OperationalInsights", "Microsoft.Insights"
) | ForEach-Object {
    [pscustomobject]@{ Provider = $_; State = az provider show -n $_ --query registrationState -o tsv }
} | Format-Table -AutoSize

az provider register -n <provider> --wait   # for anything not Registered
```

## 2. Model quota

This is the most common reason a workshop fails to start. Quota is pooled
**per subscription, per region, per model, per SKU** — so every attendee draws
from the same pool.

Terraform creates three model deployments per attendee. Capacity is in units
of 1,000 tokens per minute (TPM):

| Deployment | Model | SKU / pool | Used by |
| --- | --- | --- | --- |
| `asg-chat` | `gpt-4.1-mini` | `DataZoneStandard` | Modules 2-10 |
| `asg-judge` | `gpt-4.1-mini` | `DataZoneStandard` | Module 9 |
| `asg-router` | `model-router` | `GlobalStandard` | Module 7 |

`asg-chat` and `asg-judge` are the same model and SKU, so they share one
allowance.

| | `model_capacity` | `judge_capacity` | `router_capacity` | DataZoneStandard per attendee | GlobalStandard per attendee |
| --- | --- | --- | --- | --- | --- |
| **Per attendee** | 10 | 10 | 10 | 20 | 10 |

These are the defaults, and they carry every module. Capacity is thousands of
tokens per minute, so 10 is 10,000 TPM.

Multiply by headcount:

| Pool | Per attendee | 5 | 10 | 15 |
| --- | --- | --- | --- | --- |
| `gpt-4.1-mini` / `DataZoneStandard` | 20 | 100 | 200 | 300 |
| `model-router` / `GlobalStandard` | 10 | 50 | 100 | 150 |

If attendees hit `429` throttling while working interactively, raise
`model_capacity` — it carries the three agent calls that do the real work. Do
that per attendee rather than uniformly; one person re-running a module is not
the same as the room being under-provisioned.

Confirm the subscription has that much **free**, not just that much total:

```powershell
# Shows Limit and CurrentValue per model and SKU. Free = Limit - CurrentValue.
az cognitiveservices usage list -l <your-region> -o table
```

A quota increase takes **business days**. Request it now, not on the day.

**Deleting a stack does not immediately return its quota.** Azure AI Services
accounts soft-delete. The deleted account keeps holding its capacity, and its
name, until it is purged or ages out. If an attendee destroys and re-applies,
the second apply can fail with `InsufficientQuota` even though the portal
shows nothing deployed. Check for and purge stragglers:

```powershell
az cognitiveservices account list-deleted -o table

az cognitiveservices account purge `
    --name <account-name> --resource-group <rg-name> --location <region>
```

## 3. Per-attendee resources

Terraform creates all of the following, in one resource group per attendee:

| Resource | Count | Notes |
| --- | --- | --- |
| Resource group | 1 | `rg-agentic-support-guide-<suffix>` |
| Azure AI Services account (S0) | 1 | Hosts the Foundry project and the three model deployments |
| Foundry project | 1 | |
| Azure AI Search | 1 | `basic` by default. The `free` tier does **not** work — agentic retrieval needs the semantic ranker. |
| Storage account (Standard LRS) | 1 | Plus one `group-knowledge` blob container |
| App Service plan, Linux B1 | **2** | One for the API, one for the web app |
| Web app | 2 | One per plan |
| Log Analytics workspace | 1 | |
| Application Insights | 1 | |
| Diagnostic setting | 1 | On the AI Services account, into the workspace. |
| Role assignments | 11 | 5 to the attendee, 6 to service identities. Nobody creates these by hand. |

That is the default configuration, with every workshop feature enabled. The
`enable_app_hosting`, `enable_knowledge_plane`, `enable_model_router` and
`enable_judge_deployment` variables each remove a slice of it.

Two B1 plans per attendee is the item most often missed when sizing compute
quota: ten attendees need **20 plans and 20 web apps**, not ten.

## 4. Azure AI Search caps your class size

Each attendee needs one Search service, and Search is limited to **12 services
per subscription per region, per tier**. That is a hard ceiling on how many
attendees can share one subscription in one region — independent of model
quota. Check it, and leave room for retries:

```powershell
az search usage list --location <your-region> -o table
```

Read the `basic` and `standard` rows: `limit` minus `currentValue` is how many
more services that region will accept. A failed service that has not finished
deleting still counts.

If you need more attendees than the ceiling allows, split the group across two
regions by giving each half a different `search_location`.

**This check does not predict regional capacity.** It reports your
subscription's allowance, not whether Azure has hardware free. A region can
report 12 available and still refuse to create one — see
[Module 0](module-0-provision.md#2-pick-your-region) for that failure and how
to recover from it. Budget time for it: a failed Search create can take 15
minutes to report.

`standard` is 3.4 times the price of `basic`. Module 0 has the full recovery
sequence, including changing the SKU before the region.

## 5. Network and policy

Give this list to whoever runs the firewall. Attendees only need to know that
these have to be reachable.

| Requirement | Notes |
| --- | --- |
| <https://ai.azure.com> | The Foundry portal. Modules 4, 5, 6, 8 and 9. |
| <https://portal.azure.com> | Modules 0, 5 and 10. |
| `login.microsoftonline.com` | Entra sign-in for `az login` and every SDK call. |
| `management.azure.com` | Azure Resource Manager. Every `az` command and every Terraform operation. |
| `graph.microsoft.com` | Entra directory reads, e.g. `az ad signed-in-user show`. |
| `*.azurewebsites.net` and `*.scm.azurewebsites.net` | The attendee's own API and web app, plus the Kudu/SCM endpoint the deploy script uploads to. Some proxies do not treat a single wildcard as matching both levels — list them separately. |
| `registry.terraform.io` and `releases.hashicorp.com` | Terraform provider downloads on first `init`. |
| `*.services.ai.azure.com` | **The Foundry project endpoint.** Every agent call, every publish script and every Module 2 sample goes here. Allowing only the two hosts below is not enough. |
| `*.openai.azure.com`, `*.cognitiveservices.azure.com` | Direct model calls. |
| `*.search.windows.net` | Retrieval. |
| `*.blob.core.windows.net` | Knowledge document upload. |
| `*.in.applicationinsights.azure.com` and `api.applicationinsights.io` | Telemetry ingestion, and the queries Module 10 runs. |
| `registry.npmjs.org` and `pypi.org` / `files.pythonhosted.org` | Dependency install. |
| `aka.ms` | Redirector for the Azure CLI extension index, used by `az extension add`. |
| GitHub | Clone. A **fork per attendee** is required for the optional CI sections, along with permission to enable Actions and create environment secrets. |

Proxies that perform TLS inspection on the Azure endpoints above will break
the SDK calls. Confirm this before the workshop.

**Check your Azure Policy assignments too.** Terraform creates the AI Services
account with a public endpoint and applies tags from `infra/variables.tf`. A
policy that forbids public endpoints, restricts regions or SKUs, or requires
specific tags will fail the apply.

## 6. Cost

**Per attendee.** Measured on a real workshop resource group over a partial
month:

| Service | Measured |
| --- | --- |
| Azure AI Search (`basic`) | $18.48 |
| Microsoft Defender for Cloud | $8.85 |
| Bing Services (web knowledge source) | $2.58 |
| App Service Plan × 2 | $1.30 |
| Foundry models | $0.40 |
| Storage, Log Analytics, App Insights | pennies |

**Two lines in that table understate what you will pay**, because the
measurement covers a partial month and part of it ran on free tiers.

The Search figure is for `basic`, at $0.10 per hour. `basic` frequently has no
capacity, and the fallback is `standard`, at $0.34 per hour in the same
region. Search is the single biggest cost either way, and it bills hourly
whether or not anyone is using it.

The App Service line is understated too, because those plans spent part of the
period on the free tier. Two B1 plans alone list at roughly $26 per month.

A full month, with the stack left running, works out from the hourly rates:

| Component | `basic` | `standard` |
| --- | --- | --- |
| Azure AI Search (730 hours) | $73 | $248 |
| App Service Plan × 2 (B1) | $26 | $26 |
| Defender, Bing, models, storage, telemetry | ~$20 | ~$20 |
| **Per attendee, per month** | **~$120** | **~$295** |

Budget on the order of **$120 per attendee per month on `basic`, or $300 on
`standard`**, then multiply by headcount. The measured table above is lower
only because it is a partial month.

The cost is almost entirely idle time, not usage — but stopping the web apps
does **not** stop it. App Service plans bill for the plan, not the running
site, and Search bills hourly regardless. Only `terraform -chdir=infra
destroy` actually stops the meter. Run it when the workshop is over, and
budget for the idle days in between: do not destroy between days, because it
takes the knowledge base, index and portal-created agents with it.

## 7. Scheduling

**Module 0 is prework.** `terraform apply` alone runs 15 to 20 minutes when it
works, and Azure AI Search capacity failures can force two or three attempts
at that length. Ten people doing this on the workshop clock costs a session.
Every attendee completes Module 0 and arrives with a working stack and a green
`verify-demo.ps1`. Hold a short drop-in the day before for anyone who gets
stuck — Search capacity is the usual reason.

Modules 1 to 10 total 4 hours 25 minutes of hands-on time. Add breaks and
questions and it fills a 5-hour day with no slack. If you are running short,
the modules to cut are 7 and 10: both are self-contained, and nothing later
depends on them.

> [!IMPORTANT]
> Cutting Module 7 means skipping the module, not the router *deployment*.
> Module 8's guardrails list shows `asg-router`, so leave
> `enable_model_router` on. And whatever you cut, send attendees to
> [Module 10's Clean up](module-10-operate.md#clean-up) at the end — it is
> the only place that deletes anything, and skipping it leaves the Search
> service and two App Service plans billing.
