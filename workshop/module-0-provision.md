# Module 0 — Provision your environment

**Time:** 45-75 min, and longer if Search capacity forces a retry. Complete
this **before** the workshop.

**Goal:** a Foundry project, three model deployments, a search service and a
blob container, in a resource group of your own. Every name carries a random
suffix so a room of learners can deploy into one subscription without
colliding.

Work through the [prerequisites](README.md#prerequisites) first. Permissions,
quota and resource-provider registration are the three things that fail this
module.

```powershell
az login
az account set --subscription "<your-subscription-id>"
az account show --query "{name:name, id:id}" -o table
```

## 1. Set up the local environment

Set the console to UTF-8 first. Windows PowerShell defaults to a legacy code
page, which renders every em dash in the sample output as mojibake and will
raise `UnicodeEncodeError` on any non-ASCII character a dependency prints.

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

That lasts for the current terminal only. Set it in every terminal you open,
or make it permanent:

```powershell
[Environment]::SetEnvironmentVariable("PYTHONIOENCODING", "utf-8", "User")
```

```powershell
# Backend: Python 3.13
cd services\api
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd ..\..

# Frontend: Node 22 LTS
cd apps\web
npm install
cd ..\..
```

Run the test suite. It uses fake model clients, so it proves your environment
works without touching Azure:

```powershell
cd services\api
.\.venv\Scripts\python.exe -m pytest -q
cd ..\..
```

Every later command names `.\services\api\.venv\Scripts\python.exe` explicitly
rather than a bare `python`, so a command pasted into the wrong terminal fails
instead of running against the wrong interpreter.

## 2. Pick your region

`terraform.tfvars` is gitignored. Create it from the tracked example, or
`location` has no default and `apply` drops to an interactive prompt:

```powershell
if (-not (Test-Path infra\terraform.tfvars)) {
    Copy-Item infra\terraform.tfvars.example infra\terraform.tfvars
}
```

Open `infra/terraform.tfvars` and set `location`. Two capacity constraints
cause most failures here:

| Setting | What it controls | If it fails |
| --- | --- | --- |
| `location` | Foundry project + model deployments | Try `eastus2`, `westus3`, `centralus` |
| `search_sku` | Azure AI Search tier | Try `standard` before moving regions |
| `search_location` | Azure AI Search only | Leave empty to match `location`; set another US region once `standard` has also failed |

Search capacity is exhausted per region independently of Foundry capacity, and
it moves. Regions that worked last week fail this week, so treat any region
named here as an example rather than a recommendation.

**Check your Search allowance before you apply.** This takes a second and
rules out one of the two failure modes below:

```powershell
az search usage list --location <your-search-region> -o table
```

`limit` minus `currentValue` on the `basic` and `standard` rows is how many
more services that region will accept — the cap is 12 per tier, per
subscription, per region. If it is 0, you will fail immediately; pick another
tier or region now rather than after a 15 minute wait.

What this check **cannot** tell you is whether Azure has hardware free in that
region. A region can report 12 available and still refuse the create.

**Change the SKU before you change the region.** A Search service in a
different region from the Foundry project adds retrieval latency to every
grounded call for the whole workshop.

Capacity rejection has two shapes, and the slow one is the confusing one:

- **Fast.** `ResourcesForSkuUnavailable` or `InsufficientResourcesAvailable`
  comes back in seconds as a 400. Nothing is created.
- **Slow.** `apply` sits on `Still creating...` for 10 to 15 minutes and then
  fails with `polling after CreateOrUpdate: polling failed`. Azure leaves a
  service behind in `provisioningState: failed` with
  `"Search service failed to provision search units due to insufficient
  capacity in region"`, and Terraform does **not** record it in state.

Check which you have before re-applying:

```powershell
az search service show -n srch-asg-<suffix> -g <rg-name> `
    --query "{state:provisioningState, status:status, detail:statusDetails}"
```

If a failed service exists, delete it first. Terraform has no record of it, so
it will try to create the same name again and collide:

```powershell
az search service delete -n srch-asg-<suffix> -g <rg-name> --yes
```

The delete returns immediately but continues in the background. Re-applying
too soon fails with a different error:

```
409 Conflict ServiceDeleting: Cannot provision service named
'srch-asg-<suffix>' because a background operation is still in progress
```

Wait until the name is actually gone before re-applying. This returns
`ResourceNotFound` when you are clear:

```powershell
az search service show -n srch-asg-<suffix> -g <rg-name>
```

A successful Search create takes about 16 minutes, so a failure at the 14
minute mark looks identical to progress until it returns.

Keep any fallback in a US region. Settle both values now — changing either
later replaces the Search service rather than updating it, and a replaced
service comes back empty.

### Model capacity

`model_capacity` is in thousands of tokens per minute. The default of `10`
suits one person submitting one request at a time, which is how you will
work through these modules.

Every recommendation is three model calls — analyst, recommender, validator —
and a fourth when the validator asks for a repair. Graded evaluation in
Module 9 multiplies that per case, but still one case at a time.

If you see `AGENT_PROVIDER_THROTTLING`, you are asking for more tokens per
minute than the deployment allows. Raise `model_capacity` and re-apply.

Quota is pooled per subscription and per region:

```powershell
az cognitiveservices usage list -l westus3 -o table
```

Mind which pool. `asg-chat` and `asg-judge` are both `gpt-4.1-mini` on
`DataZoneStandard` and share an allowance; the router is a different model on
`GlobalStandard`. Use the capacity values your facilitator agreed from the
quota table in [Plan this workshop for a group](plan-this-workshop.md#2-model-quota).
The defaults below carry every module. Whichever you use, agree it as a group,
or the last person to `apply` gets `InsufficientQuota`.

```hcl
model_capacity  = 10   # the three coordinator agents
judge_capacity  = 10   # graded evaluation
router_capacity = 10   # the router deployment
```

## 3. Apply

### What the three Terraform commands do

| Command | What it does | Touches Azure? |
| --- | --- | --- |
| `init` | Downloads the providers named in [infra/providers.tf](../infra/providers.tf) into `infra/.terraform`, and prepares state | No |
| `plan` | Compares your `.tf` files to recorded state and prints what it would change | Reads only |
| `apply` | Runs `plan`, waits for you to type `yes`, then makes the changes | Yes |

`apply` runs `plan` itself, so you rarely need to run `plan` separately. The
list it prints before the prompt is the last point at which a mistake is free.

State is the file that records what Terraform already created. This workshop
keeps it locally in `infra/terraform.tfstate`, which is fine for one person
and wrong for a team — a shared backend is how two people avoid creating the
same resource twice.

### Who gets access

The workshop-user roles go to whoever runs `apply`, so
`additional_principal_ids` can stay empty. Set it only to let a colleague into
your environment. [infra/rbac.tf](../infra/rbac.tf) separately grants the API
app, the Search service and the AI Services account their own roles; those are
machine identities and that variable does not affect them.

```hcl
resource "azurerm_role_assignment" "cognitive_openai_user" {
  for_each = local.workshop_principal_ids

  scope                = azurerm_cognitive_account.ai_services.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
}
```

Three terms the rest of the workshop assumes:

- A **principal** is an identity Azure can authorize — you, a group, or an
  app's managed identity. `principal_id` is its object ID in Entra.
- A **role definition** is a named set of permitted operations.
  `Cognitive Services OpenAI User` permits inference calls and nothing else.
- A **scope** is the resource subtree the grant applies to. Here that is the
  AI Services account, so it covers every model deployment on it.

No model call in this stack uses an API key. That role on your own identity is
what makes `az login` enough to call a model from your laptop, and a managed
identity holding the same role is what makes the deployed app work without a
Foundry credential.

There is exactly one secret: [infra/api_key.tf](../infra/api_key.tf) generates
a shared key so the web tier can authenticate to the API.

### Run it

```powershell
terraform -chdir=infra init
terraform -chdir=infra apply
```

Review the plan, then type `yes`. First apply takes roughly 15-20 minutes,
almost all of it the Search service.

![The Azure portal resource group view listing the AI Services account and
project, search service, storage account, two App Service plans, two web
apps, Log Analytics and Application Insights.](images/module-0-resource-group.png)

The Search service sits in a different region from everything else — that is
the `search_location` split, and it is expected.

The three model deployments live under **Build → Models → Deployments**:

![The Foundry deployments list showing asg-judge, asg-router and asg-chat, all
with a Succeeded provisioning state.](images/module-0-model-deployments.png)

A **deployment** is a named instance of a model with its own quota. Your code
never names a model; it names a deployment. That indirection is what lets
Module 7 swap the analyst onto a router by changing one environment variable.
See [infra/model_deployments.tf](../infra/model_deployments.tf).

### What you are creating and why

| Resource | Module that needs it |
| --- | --- |
| AI Services account + Foundry project | All |
| `asg-chat` model deployment | M2 onward |
| Azure AI Search (`basic`, semantic ranker on) | M6 |
| Storage account + `group-knowledge` container | M6 |
| `asg-router` model router deployment | M7 |
| `asg-judge` model deployment | M9 |
| Log Analytics + Application Insights | M8, M9, M10 |

Semantic ranking is not optional for M6 — agentic retrieval scores with it,
so the Search `free` tier cannot be used.

### If apply fails partway

Terraform is idempotent; re-run `apply`. Three failures are common:

- **`ResourcesForSkuUnavailable` / `InsufficientResourcesAvailable`** — a
  region is out of capacity. For Search, raise `search_sku` to `standard`
  and re-apply; only if that fails too, move `search_location` to another US
  region. For anything else, change `location`. Do this one step at a time:
  each `apply` takes minutes, and you want to know which change worked.
- **`polling after CreateOrUpdate: polling failed` on the Search service** —
  the same capacity problem arriving slowly. Delete the failed service before
  re-applying; see [Pick your region](#2-pick-your-region) above.
- **`could not find role 'Azure AI User'`** — that role name is not in every
  tenant. The default `project_role_definition_name` is
  `Cognitive Services User`, which is portable. Only change it if you know
  your tenant has the newer role.
- **`KeyBasedAuthenticationNotPermitted`** — the storage account disables
  shared keys on purpose. The provider is configured with
  `storage_use_azuread = true` to match. If you see this, you have local edits
  to `infra/providers.tf`.

## 4. Generate your `.env`

Terraform knows the endpoint, deployment names and connection strings it just
created. Your code reads them from environment variables. `populate-env.ps1`
is the bridge: it runs `terraform output` and writes the values into
`services/api/.env`.

```powershell
.\scripts\populate-env.ps1
```

Read the file it wrote. It is the complete contract between the
infrastructure and the app:

```powershell
Get-Content services\api\.env
```

You should see `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`, six
`FOUNDRY_MODEL_DEPLOYMENT_*` names — one per agent role, plus the router and
the judge — `AZURE_SEARCH_ENDPOINT`, and
`APPLICATIONINSIGHTS_CONNECTION_STRING`.

Almost every value is an address rather than a credential, which is why the
file is readable. The exception is
`APPLICATIONINSIGHTS_CONNECTION_STRING`: it embeds an `InstrumentationKey`,
which is a write key for your telemetry. `populate-env.ps1` prints it as
`(hidden)` for that reason. `.env` is gitignored — keep it that way, and do
not paste it into chat or a screenshot.

The API itself does not load `.env` implicitly. `run-backend.ps1` passes
`--env-file .env` to uvicorn, so this step is required rather than optional,
and running the backend another way without that flag produces an app that
reports `provider_missing` for every request. The helper scripts do read the
file themselves, and they use `setdefault`, so a variable already set in your
shell wins over the file.

Then set your suffix by hand. `publish_prompt_agents.py` requires it, and
inside your own project it is used twice: Module 8 needs a published
`-baseline` variant addressable alongside the `-strict` agent you build by
hand, and `--delete` matches on the suffix so it removes exactly what you
published and nothing else.

```
WORKSHOP_LEARNER_SUFFIX=<your-alias>
```

`populate-env.ps1` already wrote an empty `WORKSHOP_LEARNER_SUFFIX=` line —
edit that line rather than adding a second one. The publishing scripts take
the first value they find, so an appended line looks correct and does nothing.

Confirm it took:

```powershell
Select-String -Path services\api\.env -Pattern '^WORKSHOP_LEARNER_SUFFIX='
```

Use lowercase letters, digits, or `-`, 24 characters max.

## 5. Verify

Two checks, in order, because the first one needs nothing running.

`validate_agent_definitions.py` reads every directory under `agents/`,
composes each agent's instructions the same way the runtime does, and
confirms the model deployment environment variable it names is actually set.
It makes no network calls.

```powershell
.\services\api\.venv\Scripts\python.exe scripts\validate_agent_definitions.py
```

Four agents should be listed `[ok]`, each with its `model_env` resolved to a
real deployment name. **Check that column yourself** — `<unset>` is printed
rather than treated as an error, so the exit code stays zero and step 4 may
not have written what you expected.

Note the `instructions_hash` on each line. It is a hash of the composed
instructions, and it is how you tell later whether the agent published in
Foundry still matches the file in source control.

Now start the backend in **its own terminal** and leave it running:

```powershell
.\scripts\run-backend.ps1
```

In a **second terminal**, run the end-to-end check. `verify-demo.ps1` calls
`/api/health/details` and then submits one real recommendation request, so it
exercises the model deployments and the whole coordinator:

```powershell
.\scripts\verify-demo.ps1
```

It calls `http://127.0.0.1:8000/api/health/details`, so it fails if you run it
before the backend is up. That is the most common Module 0 mistake.

`/api/health/details` is worth reading on its own — it is built by
`build_health_details` in
[services/api/app/diagnostics.py](../services/api/app/diagnostics.py), which
answers every setup question locally with no network calls, and
never echoes an endpoint or connection string back to you:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/health/details" |
  Select-Object active_provider, foundry_project_configured, model_deployments_configured, evidence_source
```

No key is needed here. `populate-env.ps1` deliberately leaves
`API_SHARED_KEY` unset for local runs — `require_api_key` in
[services/api/app/auth.py](../services/api/app/auth.py) only enforces a key
when the app is running on App Service, and it fails *closed* there if one is
missing. Module 1 is where that matters.

---

## 6. Optional — check the infrastructure in CI

**Skip this if you are not doing CI.** Nothing later depends on it.

The DevOps half of this workshop starts here: infrastructure you can review
before it exists. The `infra` job in
[.github/workflows/ci.yml](../.github/workflows/ci.yml) runs on every pull
request and on every push to `main`, and needs no Azure credentials at all:

```yaml
- run: terraform fmt -check -recursive
- run: terraform init -backend=false
- run: terraform validate
```

`-backend=false` is the interesting part. `validate` only checks
configuration — syntax, types, references between resources — so it needs no
state and no subscription. That makes it safe on a fork and on a pull request
from someone you have never met, which is exactly when you want it.

What it does **not** catch is anything that depends on reality: quota, region
capacity, whether a role name exists in your tenant. Those only appear at
`apply`, which is why this module had you read the plan rather than trust a
green check.

Run the same two commands locally before every apply:

```powershell
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

---

## Turn on New Foundry

Every portal screenshot in this workshop uses the **New Foundry** experience.
Two UIs sit behind <https://ai.azure.com> and their navigation differs, so
turn the toggle on now rather than in the middle of a module.

![The Microsoft Foundry header showing a New Foundry toggle in the on
position, followed by the Home, Discover, Build, Operate, Manage and Docs
navigation items.](images/portal-new-foundry-toggle.png)

The navigation should read **Home / Discover / Build / Operate / Manage /
Docs**.

## Check yourself

- [ ] `.venv` exists and `pytest -q` passes offline.
- [ ] `npm install` completed in `apps/web`.
- [ ] `terraform -chdir=infra output` prints a `foundry_project_endpoint`.
- [ ] `services/api/.env` exists and contains `WORKSHOP_LEARNER_SUFFIX`.
- [ ] `validate_agent_definitions.py` reports 4 valid agents.
- [ ] `verify-demo.ps1` passes with the backend running.
- [ ] You can open the Foundry portal, see your project, and the New Foundry
      toggle is on.

## Tear down

At the end of the workshop:

```powershell
terraform -chdir=infra destroy
```

Both the Cognitive Services account and the project's backing AML workspace
soft-delete. The random suffix is what lets you re-apply afterwards without
colliding with a soft-deleted name, so keep it in the naming.

A soft-deleted account also keeps holding its model quota. If you destroy and
then re-apply, the second apply can fail with `InsufficientQuota` while the
portal shows nothing deployed. Purge the leftovers to release it:

```powershell
az cognitiveservices account list-deleted -o table

az cognitiveservices account purge `
    --name <account-name> --resource-group <rg-name> --location <region>
```

---

**A note on isolation.** `Search Service Contributor` is scoped to the entire
search service, because Azure AI Search has no per-index RBAC. In this
workshop that costs you nothing — the search service is yours, not the
group's, and nobody else holds the role on it. It matters the moment this
pattern is reused somewhere with more than one team, tenant or customer on
one search service: index name prefixes are a naming convention, not a
security boundary, and anyone holding that role can delete any index on the
service. Set `grant_search_control_plane = false` and pre-create indexes out
of band for shared or long-lived environments. Module 6 makes the same point
at the place you would feel it.

**Guardrails (Module 8) need one more role.** Configuring agent guardrails in
the portal requires the **Foundry Account Owner** role, which Terraform does
not grant — it is privileged, and granting it should be a deliberate decision
rather than a side effect of `apply`. The account is yours, so assign it to
yourself when you reach Module 8. Role names in this family differ between
tenants, so list what yours actually has instead of guessing:

```powershell
az role definition list `
    --query "[?contains(roleName,'AI') || contains(roleName,'Foundry') || contains(roleName,'Cognitive')].roleName" `
    -o tsv | Sort-Object
terraform -chdir=infra output -raw ai_services_account_id
```

Filtering on `AI` alone is not enough — `Foundry Account Owner` does not
contain those letters.

Then assign the account-owner role at that scope. This needs `Owner` or
`User Access Administrator`, which is on the prerequisites list for exactly
this reason.

Next: [Module 1 — Deploy the app](module-1-deploy-the-app.md)
