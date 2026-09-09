# Prerequisites

**Read this before [Module 0](module-0-provision.md).** Every item here is
something that will stop you partway through a module if it is missing, and
several of them (quota, role assignments, app registration) depend on someone
other than you if your tenant is locked down. Check them now, not at 9am on
the day.

---

## How this workshop is set up

**You stand up your own environment. Nothing is shared with anyone.**

There is no facilitator-owned subscription to join, no pre-created Foundry
project waiting for you, and no resource that two people touch at once. You
run `terraform apply` against a subscription you control, and every resource
the workshop uses — the Foundry project, the model deployments, the search
service, the storage account, both App Service plans — is created by you,
billed to you, and destroyed by you at the end.

That is a deliberate choice. Modules 1, 7 and 9 have you deploy broken code
on purpose and watch a site go down. You cannot do that safely in an
environment somebody else is also working in.

Two consequences worth knowing up front:

- **You need real permissions**, not just access. The list below is not the
  minimum to *use* Azure AI Foundry; it is the minimum to *create* it.
- **You are your own admin.** Where a module needs an extra role, you grant
  it to yourself. Nobody is going to do it for you mid-session.

---

## 1. Azure subscription and permissions

You need a subscription you can create resources in, and enough rights in it
to hand out roles. Terraform creates role assignments — for you, for the two
App Service managed identities, and for the Search service's managed identity
— so `Contributor` alone is not sufficient.

| You need | Scope | Why | Check |
| --- | --- | --- | --- |
| `Owner`, or `Contributor` + `User Access Administrator` | Subscription (or a resource group you own) | Create resources **and** the role assignments in `infra/rbac.tf` | `az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) --include-inherited -o table` |
| Ability to register an Entra application | Tenant | `enable_api_auth = true` makes Terraform create the API's app registration | Try `az ad app create --display-name asg-prereq-check` then delete it |
| Ability to create role assignments on your own AI Services account | Resource | Module 6 (portal guardrails) and Module 7 (hosted agent identity) both need one | Covered by `Owner` / `User Access Administrator` above |

If you cannot register an application, you have two documented ways out and
should decide which before Module 0:

1. Run [scripts/setup-api-auth.ps1](../scripts/setup-api-auth.ps1) with an
   account that can, and paste the client ID into `api_client_id`.
2. Set `enable_api_auth = false`. Understand what that costs: the API is
   internet-reachable, and with auth off any caller can pick their own
   `district_id`, read every saved plan, and spend your model quota.

Sign in and pin the subscription before anything else:

```powershell
az login
az account set --subscription "<your-subscription-id>"
az account show --query "{name:name, id:id}" -o table
```

## 2. Resource providers

A fresh subscription often has these unregistered, and the failure arrives
several minutes into `terraform apply` rather than at plan time.

```powershell
$providers = @(
    "Microsoft.CognitiveServices",   # AI Services account + Foundry project
    "Microsoft.Search",              # Foundry IQ (Module 3)
    "Microsoft.Storage",             # district knowledge documents
    "Microsoft.Web",                 # App Service (Module 1)
    "Microsoft.OperationalInsights", # Log Analytics
    "Microsoft.Insights"             # Application Insights (Module 9)
)
$providers | ForEach-Object {
    [pscustomobject]@{
        Provider = $_
        State    = az provider show -n $_ --query registrationState -o tsv
    }
} | Format-Table -AutoSize
```

Anything not `Registered`:

```powershell
az provider register -n <provider> --wait
```

## 3. Quota and capacity

These are the two most common reasons Module 0 fails, and neither is fixable
by retrying.

**Model quota.** Quota is per-region *and* per-SKU. Check headroom for
`gpt-4.1-mini` on `DataZoneStandard` in the region you intend to use:

```powershell
az cognitiveservices usage list -l westus3 -o table
```

The workshop deploys three model deployments — the agents' model, a router
(Module 5) and a judge (Module 8). Defaults are modest, but a new
subscription may have zero quota. Requesting an increase takes days, so do it
now if you need it.

**Azure AI Search `basic` capacity.** Search capacity is exhausted
per-region independently of Foundry capacity, and there is no reliable way to
check it in advance — you find out at apply time with
`ResourcesForSkuUnavailable`. Module 0 handles this with a separate
`search_location` variable; just know that splitting the two regions is a
normal outcome, not a mistake. The `free` tier will not work: agentic
retrieval requires semantic ranking.

## 4. Local software

| Tool | Version | Used for | Verify |
| --- | --- | --- | --- |
| Git | any recent | Cloning this repo | `git --version` |
| PowerShell | 7 recommended (5.1 works) | Every command in these modules is PowerShell | `$PSVersionTable.PSVersion` |
| Azure CLI (`az`) | current release | Sign-in, deployments, log tailing | `az version` |
| Terraform | ≥ 1.9.0 | All infrastructure | `terraform version` |
| Python | 3.13 | Backend, agents, every script | `py -3.13 --version` |
| Node.js | 22 LTS | The React UI | `node --version` |
| Visual Studio Code | any recent | Editing `terraform.tfvars` and `.env` | `code --version` |
| GitHub CLI (`gh`) | current release | **Optional** — only Module 1's CI section | `gh --version` |

No Docker, no local database, no global `pip` or `npm` installs. Module 7
builds a container image, but Foundry builds it remotely — not on your
machine.

## 5. Accounts outside Azure

- **A GitHub account with push access to a fork or copy of this repo** —
  only if you want to do Module 1's GitHub Actions section. The rest of
  Module 1 deploys from your laptop and needs nothing from GitHub.

## 6. Cost and time

You are paying for this environment for as long as it exists.

| Resource | SKU | Billing shape |
| --- | --- | --- |
| App Service Plan × 2 | B1 Linux | Per hour, always on — App Service does not scale to zero |
| Azure AI Search | `basic` | Per hour, always on — the largest line item |
| AI Services | pay-per-token | Per request |
| Storage, Log Analytics, App Insights | consumption | Negligible at this scale |

The two App Service plans and the search service bill whether or not you are
using them, so an environment left up over a weekend costs real money for
nothing. Run `terraform -chdir=infra destroy` when you stop for the day if
you are not coming back to it soon — Module 0 is 20 minutes to stand back up.

Budget roughly two days for the full path, or one long day at pace.

## 7. Known tenant blockers

Two things that enterprise tenants commonly enforce, both of which have a
documented path through:

- **Azure Policy forcing storage `publicNetworkAccess = Disabled`.** You then
  cannot upload the district documents in Module 3 from your laptop, and
  neither can the portal. Module 3 gives you a File-knowledge-source
  alternative. The `SecurityControl = Ignore` tag in `var.tags` exempts the
  environment in some tenants; check whether yours honours it.
- **Continuous Access Evaluation rejecting the `azuread` provider's token.**
  Terraform then cannot create the API app registration even though `az`
  works fine. Fall back to
  [scripts/setup-api-auth.ps1](../scripts/setup-api-auth.ps1).

---

## Pre-flight check

Run this before Module 0. Everything should print a value.

```powershell
az account show --query "{sub:name, id:id}" -o table
az ad signed-in-user show --query "{upn:userPrincipalName, id:id}" -o table
terraform version
py -3.13 --version
node --version
az version --query '"azure-cli"' -o tsv
az cognitiveservices usage list -l <your-region> -o table
```

If all of that works, go to [Module 0](module-0-provision.md).

Back to the [workshop index](README.md).
