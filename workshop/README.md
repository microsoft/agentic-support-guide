# Agentic Support Guide — Workshop

Build a multi-agent system on Azure AI Foundry using the Microsoft Agent
Framework, deploy it, ground it, guard it, evaluate it and operate it.

**Duration:** 4 to 5 hours, plus Module 0 as prework. **Format:** hands-on;
every module is something you do.

## The scenario

You are building an internal tool for a company that owns several car
dealership groups. A manager describes a problem in their own words — slow
enquiry response, stale listings, low test-drive conversion — and the tool
returns a support plan that cites the group's own documents.

All data is synthetic. Three dealer groups (`GROUP-A`, `GROUP-B`,
`GROUP-DEMO`) each own their evidence documents and their saved plans, and a
plan for one group must never cite another group's evidence. That rule makes
the isolation and grounding work concrete. No module asks you to bring real
data.

The isolation boundary is deliberately partial: the synthetic dealership
roster carries no group id, so the dashboard and dealership lists are shared.
Evidence retrieval and saved plans are the group-scoped surfaces, and those
are the ones Module 6 has you attack.

## What you will learn

| # | Module | You will be able to |
| --- | --- | --- |
| 0 | Provision your environment | Stand up a Foundry project, model deployments, Azure AI Search and storage with Terraform |
| 1 | Deploy the app | Ship an API and UI to App Service and prove your build is the one serving |
| 2 | Your first agent | Write an agent, give it a tool, and hold a multi-turn session |
| 3 | Workflows | Build a `WorkflowBuilder` graph with executors, edges and a conditional repair loop |
| 4 | Prompt agents | Define an agent declaratively and publish versions to Foundry |
| 5 | Hosted agents | Run your own code as a Foundry-managed agent with its own identity |
| 6 | Ground it with RAG | Wire retrieval into the running app and enforce per-group isolation |
| 7 | Model router | Route across models and measure what it costs and returns |
| 8 | Guardrails | Measure what the platform blocks and what only your code can |
| 9 | Evaluation | Grade agent output numerically and gate regressions |
| 10 | Operate | Trace a request, diagnose a failed deployment, and forecast cost |

Modules 2 and 3 matter most if you have never written an agent. Everything
after them assumes you know what an agent, a tool, an executor and an edge are.

## Before the workshop

Everything in this section must be done **before** the first module. Nothing
here is part of the workshop time budget.

Each learner deploys a complete stack of their own: resource group, Foundry
project, three model deployments, search service, storage and two App
Services. **The subscription is the only thing shared between learners**,
which means shared model quota and globally unique resource names.

The tables below are written **per learner**. Multiply by your own headcount.

### 1. Azure permissions

Per learner, on the shared subscription:

| Role | Scope | Why |
| --- | --- | --- |
| `Owner` — or `Contributor` **and** `User Access Administrator` | Subscription | Terraform creates a resource group *and* role assignments inside it. `Contributor` alone fails on the role assignments. |

Terraform then assigns each learner five roles in their own resource group
(`Cognitive Services OpenAI User`, the project role, `Search Service
Contributor`, `Search Index Data Contributor`, `Storage Blob Data
Contributor`) and six more to the app and service identities. Nobody needs to
create those by hand.

Two roles Terraform does **not** grant:

| Role | Scope | Needed for | Required? |
| --- | --- | --- | --- |
| Foundry Account Owner | Learner's own AI Services account | Configuring agent guardrails (Module 8) | **Yes** — Module 8's main path |
| Ability to create an app registration | Entra tenant | CI sections of Modules 1 and 9 | Optional |

**No user sign-in is configured.** The API is protected by a shared key that
Terraform generates, so the main path needs no app registration.

Foundry Account Owner is privileged, so `apply` does not grant it as a side
effect. The account belongs to the learner, and a learner with
`Owner`/`User Access Administrator` on the subscription can assign it to
themselves when Module 8 asks. **If your tenant restricts self-assignment,
arrange it before the workshop.**

Module 5 also has learners grant `Cognitive Services OpenAI User` to a hosted
agent's managed identity by hand. Terraform cannot pre-create that assignment
because the identity does not exist until the agent is deployed. The
subscription-level permission above already covers it.

Verify per learner:

```powershell
az login
az account set --subscription "<your-subscription-id>"
az role assignment list --assignee (az ad signed-in-user show --query id -o tsv) `
    --include-inherited -o table
```

### 2. Resource providers

Registered **once per subscription**, not per learner. An unregistered
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

### 3. Model quota

This is the most common reason a workshop fails to start. Quota is pooled
**per subscription, per region, per model, per SKU** — so every learner draws
from the same pool.

Terraform creates three model deployments per learner. Capacity is in units of
1,000 tokens per minute (TPM):

| Deployment | Model | SKU / pool | Used by |
| --- | --- | --- | --- |
| `asg-chat` | `gpt-4.1-mini` | `DataZoneStandard` | Modules 2-10 |
| `asg-judge` | `gpt-4.1-mini` | `DataZoneStandard` | Module 9 |
| `asg-router` | `model-router` | `GlobalStandard` | Module 7 |

`asg-chat` and `asg-judge` are the same model and SKU, so they share one
allowance.

| | `model_capacity` | `judge_capacity` | `router_capacity` | DataZoneStandard per learner | GlobalStandard per learner |
| --- | --- | --- | --- | --- | --- |
| **Per learner** | 10 | 10 | 10 | 20 | 10 |

These are the defaults, and they carry every module. Capacity is thousands of
tokens per minute, so 10 is 10,000 TPM.

Multiply by headcount:

| Pool | Per learner | 5 learners | 10 learners | 15 learners |
| --- | --- | --- | --- | --- |
| `gpt-4.1-mini` / `DataZoneStandard` | 20 | 100 | 200 | 300 |
| `model-router` / `GlobalStandard` | 10 | 50 | 100 | 150 |

If learners hit `429` throttling while working interactively, raise
`model_capacity` — it carries the two agent calls that do the real work.
Do that per learner rather than uniformly; one person re-running a module is
not the same as the room being under-provisioned.

Confirm the subscription has that much **free**, not just that much total:

```powershell
# Shows Limit and CurrentValue per model and SKU. Free = Limit - CurrentValue.
az cognitiveservices usage list -l <your-region> -o table
```

A quota increase takes **business days**. Request it now, not on the day.

**Deleting a stack does not immediately return its quota.** Azure AI Services
accounts soft-delete. The deleted account keeps holding its capacity, and its
name, until it is purged or ages out. If a learner destroys and re-applies,
the second apply can fail with `InsufficientQuota` even though the portal
shows nothing deployed. Check for and purge stragglers:

```powershell
az cognitiveservices account list-deleted -o table

az cognitiveservices account purge `
    --name <account-name> --resource-group <rg-name> --location <region>
```

### 4. Other per-learner capacity

Terraform creates all of the following, in one resource group per learner:

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
| Role assignments | 11 | 5 to the learner, 6 to service identities. Nobody creates these by hand. |

That is the default configuration, with every workshop feature enabled. The
`enable_app_hosting`, `enable_knowledge_plane`, `enable_model_router` and
`enable_judge_deployment` variables each remove a slice of it.

Two B1 plans per learner is the item most often missed when sizing compute
quota: ten learners need **20 plans and 20 web apps**, not ten.

#### Azure AI Search caps your class size

Each learner needs one Search service, and Search is limited to **12 services
per subscription per region, per tier**. That is a hard ceiling on how many
learners can share one subscription in one region — independent of model
quota. Check it, and leave room for retries:

```powershell
az search usage list --location <your-region> -o table
```

Read the `basic` and `standard` rows: `limit` minus `currentValue` is how many
more services that region will accept. A failed service that has not finished
deleting still counts.

If you need more learners than the ceiling allows, split the group across two
regions by giving each half a different `search_location`.

**This check does not predict regional capacity.** It reports your
subscription's allowance, not whether Azure has hardware free. A region can
report 12 available and still refuse to create one — see
[Module 0](module-0-provision.md#2-pick-your-region) for that failure and how
to recover from it. Budget time for it: a failed Search create can take 15
minutes to report.

If `terraform apply` reports `ResourcesForSkuUnavailable` for Search, change
the SKU before you change the region: set `search_sku = "standard"` in the
same region first, and only move `search_location` if that also fails. A
Search service in a different region from the Foundry project adds retrieval
latency to every grounded call for the rest of the workshop.
[Module 0](module-0-provision.md#2-pick-your-region) has the full recovery
sequence, including deleting the failed service Terraform did not record.
`standard` is 3.4 times the price of `basic` — see [Cost](#cost).

Keep `search_name_prefix` at 16 characters or fewer. The storage account name
is `st<prefix><suffix>` truncated to 24 characters, so a longer prefix eats
the random suffix that keeps learners from colliding.

### 5. Local software

Per learner, on their own machine. **Windows is assumed** — the modules use
the `py` launcher and `.venv\Scripts\` paths, and every script is PowerShell.
Learners also need permission to run local PowerShell scripts.

| Tool | Minimum | Tested | Verify |
| --- | --- | --- | --- |
| Windows | 10 / 11 | 11 | |
| Git | 2.40 | 2.55 | `git --version` |
| PowerShell | 7.4 | 7.6 | `$PSVersionTable.PSVersion` |
| Azure CLI | 2.84 | 2.84 | `az version` |
| Azure CLI `application-insights` extension | any | 1.2.3 | `az extension add -n application-insights` |
| Terraform | 1.9.0 | 1.16 | `terraform version` |
| Python | 3.13 | 3.13.7 | `py -3.13 --version` |
| Node.js | 20 LTS | 22 LTS | `node --version` |
| Visual Studio Code | 1.90 | current | `code --version` |
| GitHub CLI — optional, CI sections only | 2.40 | current | `gh --version` |
| Graphviz — optional, only to regenerate the workflow diagram | 12 | 16.1 | `dot -V` |

Do not pin an older Azure CLI. `az search usage list`, which the pre-flight
check and Module 0 both rely on, is missing from older builds.

No Docker, no .NET, and no global `pip` or `npm` installs. Everything the
workshop runs is Python, Node or Terraform. Modules 2 and 3 read and edit
Python, so learners should be comfortable with functions, classes and
`async`/`await`.

**Set PowerShell to UTF-8.** Windows PowerShell defaults to a legacy code
page, which renders the em dashes in the sample output as mojibake and raises
`UnicodeEncodeError` on any non-ASCII character a dependency prints:

```powershell
[Environment]::SetEnvironmentVariable("PYTHONIOENCODING", "utf-8", "User")
```

Reopen the terminal afterwards.

**One clone per learner, and one Windows user account per learner.** Terraform
state is a local file in `infra/`, and the deploy script stages into a fixed
directory under `%TEMP%`. Two learners sharing a folder or a signed-in Windows
account will overwrite each other.

### 6. Access and network

| Requirement | Notes |
| --- | --- |
| <https://ai.azure.com> | The Foundry portal. Modules 4, 5, 6, 8 and 9. |
| <https://portal.azure.com> | Modules 0, 5 and 10. |
| `login.microsoftonline.com` | Entra sign-in for `az login` and every SDK call. |
| `management.azure.com` | Azure Resource Manager. Every `az` command and every Terraform operation. |
| `graph.microsoft.com` | Entra directory reads, e.g. `az ad signed-in-user show` in the pre-flight check. |
| `*.azurewebsites.net` and `*.scm.azurewebsites.net` | The learner's own API and web app, plus the Kudu/SCM endpoint the deploy script uploads to. Some proxies do not treat a single wildcard as matching both levels — list them separately. |
| `registry.terraform.io` and `releases.hashicorp.com` | Terraform provider downloads on first `init`. |
| `*.services.ai.azure.com` | **The Foundry project endpoint.** Every agent call, every publish script and every Module 2 sample goes here. Allowing only the two hosts below is not enough. |
| `*.openai.azure.com`, `*.cognitiveservices.azure.com` | Direct model calls. |
| `*.search.windows.net` | Retrieval. |
| `*.blob.core.windows.net` | Knowledge document upload. |
| `*.in.applicationinsights.azure.com` and `api.applicationinsights.io` | Telemetry ingestion, and the queries Module 10 runs. |
| `registry.npmjs.org` and `pypi.org` / `files.pythonhosted.org` | Dependency install. |
| `aka.ms` | Redirector for the Azure CLI extension index, used by `az extension add`. |
| GitHub | Clone. A **fork per learner** is required for the optional CI sections, along with permission to enable Actions and create environment secrets. |

Proxies that perform TLS inspection on the Azure endpoints above will break
the SDK calls. Confirm this before the workshop.

**Check your Azure Policy assignments too.** Terraform creates the AI Services
account with a public endpoint and applies tags from `infra/variables.tf`. A
policy that forbids public endpoints, restricts regions or SKUs, or requires
specific tags will fail the apply.

### 7. Portal experience

Every portal screenshot uses the **New Foundry** experience. Two UIs sit
behind <https://ai.azure.com> and their navigation differs.

![The Microsoft Foundry header showing a New Foundry toggle in the on
position, followed by the Home, Discover, Build, Operate, Manage and Docs
navigation items.](images/portal-new-foundry-toggle.png)

Turn the toggle on before you start. The navigation should read **Home /
Discover / Build / Operate / Manage / Docs**.

### 8. Pre-flight check

Every line should print a value. Run this the day before, not on the day.

```powershell
az account show --query "{sub:name, id:id}" -o table
az ad signed-in-user show --query "{upn:userPrincipalName, id:id}" -o table
terraform version
py -3.13 --version
node --version
git --version
az version --query '"azure-cli"' -o tsv
az cognitiveservices usage list -l <your-region> -o table
az search usage list --location <your-search-region> -o table
```

## Cost

**Per learner.** Measured on a real workshop resource group over a partial
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

The Search figure is for `basic`, at $0.10 per hour. `basic` frequently has
no capacity — see the note above — and the fallback is `standard`, at $0.34
per hour in the same region. Search is the single biggest cost either way,
and it bills hourly whether or not anyone is using it.

The App Service line is understated too, because those plans spent part of
the period on the free tier. Two B1 plans alone list at roughly $26 per
month.

A full month, with the stack left running, works out from the hourly rates:

| Component | `basic` | `standard` |
| --- | --- | --- |
| Azure AI Search (730 hours) | $73 | $248 |
| App Service Plan × 2 (B1) | $26 | $26 |
| Defender, Bing, models, storage, telemetry | ~$20 | ~$20 |
| **Per learner, per month** | **~$120** | **~$295** |

Budget on the order of **$120 per learner per month on `basic`, or $300 on
`standard`**, then multiply by headcount. The measured table above is lower
only because it is a partial month.

The cost is almost entirely idle time, not usage — but stopping the web apps
does **not** stop it. App Service plans bill for the plan, not the running
site, and Search bills hourly regardless. Only `terraform -chdir=infra
destroy` actually stops the meter. Run it when the workshop is over, and
budget for the idle days in between: do not destroy between days, because it
takes the knowledge base, index and portal-created agents with it.

## Modules

**Module 0 is prework.** `terraform apply` alone runs 15 to 20 minutes when it
works, and Azure AI Search capacity failures can force two or three attempts
at that length. Ten people doing this on the workshop clock costs a session.
Every learner completes Module 0 and arrives with a working stack and a green
`verify-demo.ps1`. Facilitators should hold a short drop-in the day before for
anyone who gets stuck — Search capacity is the usual reason.

| # | Module | Time |
| --- | --- | --- |
| 0 | [Provision your environment](module-0-provision.md) | **Prework**, 45-75 min |
| 1 | [Deploy the app](module-1-deploy-the-app.md) | 25 min |
| 2 | [Your first agent](module-2-first-agent.md) | 25 min |
| 3 | [Workflows](module-3-workflows.md) | 35 min |
| 4 | [Prompt agents](module-4-prompt-agents.md) | 25 min |
| 5 | [Hosted agents](module-5-hosted-agents.md) | 30 min |
| 6 | [Ground it with RAG](module-6-rag.md) | 35 min |
| 7 | [Model router](module-7-model-router.md) | 20 min |
| 8 | [Guardrails](module-8-guardrails.md) | 25 min |
| 9 | [Evaluation](module-9-evaluation.md) | 25 min |
| 10 | [Operate](module-10-operate.md) | 20 min |

Modules 1 to 10 total 4 hours 25 minutes of hands-on time. Add breaks and
questions and it fills a 5-hour day with no slack. If you are running short,
the modules to cut are 7 and 10: both are self-contained, and nothing later
depends on them.

## The domain rule

Nothing this system produces is a determination — not a pricing, credit,
compliance, safety or staffing decision. Every output carries a human-review
caveat and the validator rejects drafts that lack one. This shapes the agent
instructions, the validator and the evaluation criteria, and you will see it
enforced in code.

## Orchestration pattern

Sequential, with one conditional repair edge — not handoff, concurrent, group
chat or magentic. [docs/orchestration-patterns.md](../docs/orchestration-patterns.md)
covers what each of those is and why this one was chosen.

## Repository layout

| Path | Contents |
| --- | --- |
| `agents/` | Agent definitions — `agent.md` + `manifest.yaml` |
| `contracts/v1/` | JSON Schemas for every inter-agent message |
| `services/api/` | FastAPI backend, workflow graph, evidence retrieval |
| `apps/web/` | React UI |
| `infra/` | Terraform |
| `evals/` | Synthetic cases and expected checks |
| `scripts/` | Publish, validate, evaluate, provision, deploy, smoke test |
| `workshop/code/` | The runnable samples used in Modules 2 and 3 |

Complete [Module 0](module-0-provision.md) before the workshop, then start at
[Module 1](module-1-deploy-the-app.md).
