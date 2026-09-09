# Module 0 — Provision your environment

**Who runs this:** you, in your own subscription. Nothing in this workshop is
shared — there is no facilitator-owned environment to join, and every
resource below belongs to you.

**Time:** about 20 minutes, mostly waiting.

**You will have at the end:** a Foundry project, three model deployments, a
search service, and a blob container — all in your own resource group, named
with a random suffix so that a redeploy after `destroy` does not collide with
Azure's soft-delete tombstones or with globally-unique names someone else
already took.

---

## Before you start

Work through [Prerequisites](prerequisites.md) first. Permissions, quota and
resource-provider registration are the three things that fail this module,
and all three are cheaper to check now than to discover mid-apply.

```powershell
az login
az account set --subscription "<your-subscription-id>"
```

Confirm you are on the right subscription. Everything below lands there.

```powershell
az account show --query "{name:name, id:id}" -o table
```

## 1. Set up the local dev environment

Nothing later works without this, and nothing creates it for you.

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

Check it worked, entirely offline:

```powershell
cd services\api
.\.venv\Scripts\python.exe -m pytest -q
cd ..\..
```

Every later command uses `.\services\api\.venv\Scripts\python.exe` explicitly
rather than a bare `python`, so you never have to remember to activate
anything.

## 2. Pick your region

`terraform.tfvars` is gitignored, so a fresh clone does not have one. Create
it from the tracked example first — without this, `location` has no default,
`terraform apply` drops to an interactive prompt, and every tfvars edit in
this module lands in a file Terraform never reads:

```powershell
if (-not (Test-Path infra\terraform.tfvars)) {
    Copy-Item infra\terraform.tfvars.example infra\terraform.tfvars
}
```

Now open `infra/terraform.tfvars` and set `location`.

Two independent capacity constraints bite here, and they are the most common
reason this module fails:

| Setting | What it controls | If it fails |
| --- | --- | --- |
| `location` | Foundry project + model deployments | Try `eastus2`, `westus3`, `swedencentral` |
| `search_location` | Azure AI Search only | Leave empty to match `location`; set it separately when Search has no capacity |

Search capacity is exhausted per-region *independently* of Foundry capacity.
On 2026-09-03 the `basic` Search SKU had no capacity in either `westus3` or
`eastus2`, while `westus2` was fine. Cross-region only costs retrieval
latency, so splitting them is a normal outcome, not a mistake.

### Model capacity is the setting you will feel first

`model_capacity` is in thousands of tokens per minute, and the default of
`10` is sized for one person clicking one request at a time. That is enough
for Modules 2, 3 and 4, where you submit a request and read the answer.

It stops being enough the moment anything runs in parallel. Every
recommendation is **four model calls**, so Module 8's graded evaluation — six
cases, each answered and then graded — and the load test in Module 5 both fan
out fast. Measured against the deployed app:

| `model_capacity` | 15 concurrent | 30 concurrent |
| --- | --- | --- |
| 10 | 2/15 succeeded | 1/30 succeeded |
| 300 | 15/15 | 30/30 |

At 10, the rest fail with `AGENT_PROVIDER_THROTTLING`. The app handles it
cleanly — no crash, a typed error — but the run does not complete.

Check your headroom before raising it, because quota is per-region and
per-SKU:

```powershell
az cognitiveservices usage list -l westus3 -o table
```

Then set all three, up to whatever your quota allows, since Modules 5 and 8
use their own deployments:

```hcl
model_capacity  = 300   # the three coordinator agents
judge_capacity  = 50    # Module 8 evaluation
router_capacity = 100   # Module 5 routing
```

You can reproduce the measurement yourself once deployed:

```powershell
python scripts\load_test.py --waves 30
```

## 3. Apply

There is no access list to fill in. Every role this stack creates goes to
whoever runs `apply`, so `additional_principal_ids`, `facilitator_object_ids`
and `district_assignments` can all stay empty — empty means you, and you are
the only identity that needs to reach this environment. Set them only if you
deliberately want to let a colleague into your subscription.

```powershell
terraform -chdir=infra init
terraform -chdir=infra apply
```

Review the plan, then type `yes`.

### What you are creating and why

| Resource | Module that needs it |
| --- | --- |
| AI Services account + Foundry project | All |
| `asg-chat` model deployment | M2-M4 |
| Azure AI Search (`basic`, semantic ranker on) | M3 |
| Storage account + `district-knowledge` container | M3 |
| `asg-router` model router deployment | M5 |
| `asg-judge` model deployment | M8 |
| Log Analytics + Application Insights | M6, M8, M9 |

Semantic ranking is not optional for M3 — agentic retrieval scores with it,
so the Search `free` tier cannot be used.

### If apply fails partway

Terraform is idempotent; re-run `apply`. Three failures are common:

- **`ResourcesForSkuUnavailable` / `InsufficientResourcesAvailable`** — a
  region is out of capacity. Change `search_location` (Search) or `location`
  (everything else) and re-apply.
- **`could not find role 'Azure AI User'`** — that role name is not in every
  tenant. The default `project_role_definition_name` is
  `Cognitive Services User`, which is portable. Only change it if you know
  your tenant has the newer role.
- **`KeyBasedAuthenticationNotPermitted`** — the storage account disables
  shared keys on purpose. The provider is configured with
  `storage_use_azuread = true` to match. If you see this, you have local edits
  to `infra/providers.tf`.

## 4. Generate your `.env`

```powershell
.\scripts\populate-env.ps1
```

This writes `services/api/.env` from the Terraform outputs. Nothing in this
repo loads `.env` implicitly, so this step is required, not optional.

Then set your suffix. `publish_prompt_agents.py` requires it, and inside your
own project it earns its keep twice: Module 6 publishes two variants of one
agent and needs them separately addressable, and `--delete` matches on the
suffix so it removes exactly what you published and nothing else.

```powershell
# Replace the placeholder rather than appending: populate-env.ps1 already
# writes an empty WORKSHOP_LEARNER_SUFFIX=, and the first value wins.
$envPath = "services\api\.env"
(Get-Content $envPath) -replace '^WORKSHOP_LEARNER_SUFFIX=.*$', 'WORKSHOP_LEARNER_SUFFIX=<your-alias>' |
    Set-Content $envPath
Select-String -Path $envPath -Pattern '^WORKSHOP_LEARNER_SUFFIX='
```

Use lowercase letters, digits, or `-`, 24 characters max.

## 5. Verify

First the offline checks — no backend needed:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\validate_agent_definitions.py
```

You should see four agents listed as `[ok]`.

Then start the backend in **its own terminal** and leave it running:

```powershell
.\scripts\run-backend.ps1
```

In a **second terminal**, run the end-to-end check:

```powershell
.\scripts\verify-demo.ps1
```

`verify-demo.ps1` calls `http://127.0.0.1:8000/api/health/details`, so it
fails if you run it before the backend is up. That is the most common
Module 0 mistake.

---

## Check yourself

- [ ] `.venv` exists and `pytest -q` passes offline.
- [ ] `npm install` completed in `apps/web`.
- [ ] `terraform -chdir=infra output` prints a `foundry_project_endpoint`.
- [ ] `services/api/.env` exists and contains `WORKSHOP_LEARNER_SUFFIX`.
- [ ] `validate_agent_definitions.py` reports 4 valid agents.
- [ ] `verify-demo.ps1` passes with the backend running.
- [ ] You can open the Foundry portal and see your project.

## Tear down

At the end of the workshop:

```powershell
terraform -chdir=infra destroy
```

Both the Cognitive Services account and the project's backing AML workspace
soft-delete. The random suffix is what lets you re-apply afterwards without
colliding with the tombstone, so do not remove it from the naming.

---

**A note on isolation.** `Search Service Contributor` is scoped to the entire
search service, because Azure AI Search has no per-index RBAC. In this
workshop that costs you nothing — the service is yours and nobody else holds
the role. It matters the moment this pattern is reused somewhere with more
than one team, tenant or customer in it: index name prefixes are a naming
convention, not a security boundary, and anyone holding that role can delete
any index on the service. Set `grant_search_control_plane = false` and
pre-create indexes out of band for shared or long-lived environments. Module
3 makes the same point at the place you would feel it.

**Guardrails (Module 6) need one more role.** Configuring agent guardrails in
the portal requires the **Foundry Account Owner** role, which Terraform does
not grant — it is privileged, and granting it should be a deliberate decision
rather than a side effect of `apply`. The account is yours, so assign it to
yourself when you reach Module 6. Role names in this family differ between
tenants, so list what yours actually has instead of guessing:

```powershell
az role definition list --query "[?contains(roleName, 'AI')].roleName" -o tsv
terraform -chdir=infra output -raw ai_services_account_id
```

Then assign the account-owner role at that scope. This needs `Owner` or
`User Access Administrator`, which is on the prerequisites list for exactly
this reason.

Next: [Module 1 — Deploy the app to Azure](module-1-deploy-app.md)
