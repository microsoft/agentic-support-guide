# Module 0 — Provision your environment

**Who runs this:** the facilitator, once, before the workshop. Learners can
also run it solo against their own subscription.

**Time:** about 20 minutes, mostly waiting.

**You will have at the end:** a Foundry project, three model deployments, a
search service, and a blob container — all named with a random suffix so a
whole room can deploy into one subscription without colliding.

---

## Before you start

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

# Frontend: Node 20+
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

Open `infra/terraform.tfvars` and set `location`.

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

## 3. Grant access to your learners

By default every role goes only to whoever runs `apply`. For a shared
workshop, add everyone else in `infra/terraform.tfvars`:

```hcl
additional_principal_ids = [
  "00000000-0000-0000-0000-000000000001",
]
```

Above roughly ten people, use one Entra **group** object ID instead —
membership changes then need no re-apply:

```powershell
az ad group show --group "ASG Workshop" --query id -o tsv
az ad user show --id someone@example.invalid --query id -o tsv
```

## 4. Apply

```powershell
terraform -chdir=infra init
terraform -chdir=infra apply
```

Review the plan, then type `yes`.

### What you are creating and why

| Resource | Module that needs it |
| --- | --- |
| AI Services account + Foundry project | All |
| `asg-chat` model deployment | M1, M2 |
| Azure AI Search (`basic`, semantic ranker on) | M2 |
| Storage account + `district-knowledge` container | M2 |
| `asg-router` model router deployment | M3 |
| `asg-judge` model deployment | M6 |
| Log Analytics + Application Insights | M4, M6 |

Semantic ranking is not optional for M2 — agentic retrieval scores with it,
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

## 5. Generate your `.env`

```powershell
.\scripts\populate-env.ps1
```

This writes `services/api/.env` from the Terraform outputs. Nothing in this
repo loads `.env` implicitly, so this step is required, not optional.

Then set your own learner suffix — this is what keeps your agents separate
from everyone else's in a shared project:

```powershell
Add-Content services\api\.env "WORKSHOP_LEARNER_SUFFIX=<your-alias>"
```

Use lowercase letters, digits, or `-`, 24 characters max.

## 6. Verify

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

**A note on isolation, if you are the facilitator.**
`Search Service Contributor` is scoped to the entire search service. Azure AI
Search has no per-index RBAC, so index name prefixes are a naming convention,
not a security boundary — any learner holding that role can delete any other
learner's index. That is fine in a throwaway workshop subscription and not
fine anywhere else. Set `grant_search_control_plane = false` and pre-create
indexes yourself for shared or long-lived environments.

**Guardrails (Module 4) need more.** Configuring guardrails requires the
**Foundry Account Owner** role, which Terraform does not grant — it is a
privileged role that should be a deliberate decision, not a side effect of
`apply`. Either assign it to learners yourself, or run Module 4 as a
facilitator-led demonstration. Module 4 says the same thing.

Next: [Module 1 — Your first prompt agent](module-1-prompt-agent.md)
