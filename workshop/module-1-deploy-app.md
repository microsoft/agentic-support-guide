# Module 1 — Deploy the app to Azure

**Time:** about 45 minutes, much of it waiting on a build.

**You will have at the end:** your API and UI running on Azure App Service,
deployed by you, with a health check you can point at.

---

## Why this comes before any agent work

The rest of the workshop is GenAIOps — prompts, grounding, guardrails,
evaluation. None of it matters if you cannot ship the thing that uses it.

So this module is plain DevOps: build an artifact, deploy it, verify it,
know where the logs are. The same loop you would automate in CI, run once by
hand so the automation later is not a black box.

## The shape of what you are deploying

| Piece | Runs on | Why separate |
| --- | --- | --- |
| API (FastAPI) | `app-asg-api-<suffix>`, its own App Service Plan | A UI redeploy must not restart the API |
| UI (React/Vite) | `app-asg-web-<suffix>`, its own plan | Static bundle, different runtime, different scaling |
| Agents | Foundry (Modules 2 and 7) | Not your servers at all |

Two plans is a deliberate choice. One plan would be cheaper and would couple
the two deployments together — which is exactly the coupling that makes
teams afraid to ship.

## 1. Confirm Module 0 created the hosting

```powershell
terraform -chdir=infra output api_url
terraform -chdir=infra output web_url
```

Both should print a URL. Visit the API one — you will get a default App
Service page, because nothing is deployed yet. That is the correct starting
point.

## 2. Look at what the deploy script does before running it

Open [scripts/deploy-app.ps1](../scripts/deploy-app.ps1). Two details are
worth understanding, because both are the kind of thing that silently
produces a broken deployment:

**The API zip preserves the repo layout.**
`app/contracts_registry.py` finds `contracts/` with
`Path(__file__).parents[3]`, and `prompt_envelope.py` finds `agents/` with
`parents[4]`. Zip `services/api/*` at the root and those resolve to `/home`,
so the app dies at import with a confusing path error. The zip therefore
contains `services/api/`, `contracts/` and `agents/`, and the startup
command is:

```
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir services/api
```

**The UI's API URL is baked in at build time.** Vite inlines
`VITE_API_BASE_URL` into the bundle. The client defaults to a relative
`/api`, which cannot work here because the UI and API are different hosts.
The script sets it to `<api_url>/api` before `npm run build`.

## 3. Deploy

```powershell
.\scripts\deploy-app.ps1
```

The API deploy triggers an Oryx build on App Service — it uploads your zip,
then runs `pip install` server-side from the `requirements.txt` at the
package root. Expect several minutes.

The script does one thing you should notice. It stamps every package with a
`build_id` and then polls `/api/health` until that exact value comes back:

```
Waiting for build 20260905-123439-620 to serve ...
  status   = ok
  build_id = 20260905-123439-620
```

That check exists because **a successful deploy does not prove the new code
is running.** Oryx can skip a rebuild and the previous worker can keep
answering, so the deployment goes green while your change is nowhere. This
happened while building the workshop, and it cost an hour of debugging a bug
that had already been fixed. Module 9 makes you reproduce it deliberately.

## 4. Verify

```powershell
python scripts\smoke_test.py
```

This checks the things a health endpoint cannot:

| Check | Why it is not obvious |
| --- | --- |
| UI bundle targets the deployed API | A UI can load perfectly and call `localhost` |
| CORS allows the UI origin | Browser-only failure; `curl` never sees it |
| Deep links fall back to the SPA | `/dashboard` 404s without `--spa` |
| A real agent call returns citations | Health checks never call a model |
| Which provider served the evidence | Fixtures and real grounding look identical |
| No cross-district citations | The isolation claim, actually tested |

Then open the UI URL and submit a support request. It goes UI → API →
Foundry → back.

## 5. Break the build, then find out why

Deployments fail. Knowing where to look is the skill.

This module breaks the **build**. Module 7 breaks a **hosted agent**, and
Module 9 breaks the **running app** — three different failures with three
different signals, which is why each gets its own exercise.

```powershell
$rg  = terraform -chdir=infra output -raw resource_group_name
$app = terraform -chdir=infra output -raw api_app_name

az webapp log tail --resource-group $rg --name $app
```

Add a nonexistent package to `services/api/requirements.txt` and redeploy.
The Oryx build fails server-side, so the deploy never reaches the startup
stage and the previously deployed code keeps running. Remove it and
redeploy.

Note the distinction, because it decides how urgent the failure is: a build
that fails leaves the old version serving. A build that succeeds and then
cannot *start* takes the site down. You will do that second one in Module 9.

## 6. Notice the identity

The deployed API does **not** run as you. It has its own system-assigned
managed identity, and Module 0 granted *that identity* three roles:

| Scope | Role | Needed for |
| --- | --- | --- |
| AI Services account | `Cognitive Services OpenAI User` | Direct model calls |
| Foundry **project** | `Cognitive Services User` | Agent calls |
| Search service | `Search Index Data Reader` | Module 3 grounding |

```powershell
az webapp identity show --resource-group $rg --name $app --query principalId -o tsv
```

The first two look redundant and are not. Account-scope inference and
project-scope agent calls are separate RBAC scopes. With only the first, the
app starts, `/api/health` reports `ok`, and every agent call fails with
`AGENT_PROVIDER_AUTH_DENIED` — which is exactly what happened while building
this workshop. A health check that does not call a model cannot catch it.
That is why `smoke_test.py` makes a real request.

This is also why no key or connection string for Foundry appears anywhere in
the deployment. `DefaultAzureCredential` resolves to this identity in Azure
and to your `az login` locally, so the same code works in both places.

Forgetting to grant the *app's* identity — as opposed to your own — is one
of the most common reasons an app works locally and returns 403 in Azure.

## 7. Automate the loop you just ran

[.github/workflows/deploy.yml](../.github/workflows/deploy.yml) is the same
sequence: package, deploy, confirm the `build_id`, smoke test. It
authenticates with federated credentials rather than a stored publish
profile, so there is no secret to leak or rotate.

It is `workflow_dispatch` only. A workshop repo should not deploy to a
shared subscription on every push.

To enable it, set these repository variables from your Terraform outputs:

```powershell
terraform -chdir=infra output
# AZURE_RESOURCE_GROUP, AZURE_API_APP_NAME, AZURE_WEB_APP_NAME,
# AZURE_API_URL, AZURE_WEB_URL
```

and configure `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
as secrets against a federated credential.

Note the `concurrency` block. Two overlapping deploys to one App Service
make the first fail to start — also learned the hard way.

---

## Check yourself

- [ ] Both URLs serve your application, not the App Service placeholder.
- [ ] `scripts\smoke_test.py` passes every check.
- [ ] You submitted a request through the deployed UI.
- [ ] You caused a build failure and found it in the logs.
- [ ] You can state the API's principal ID and why it needs three roles.

## What you should be able to explain

- Why the API and UI have separate App Service Plans.
- Why the zip layout matters for this application specifically.
- Why the UI's API URL cannot be changed without rebuilding.
- Why a green deploy does not prove the new code is serving.
- Why account-scope and project-scope RBAC are both required.
- What `DefaultAzureCredential` resolves to in Azure versus on your laptop.

Next: [Module 2 — Your first prompt agent](module-2-prompt-agent.md)
