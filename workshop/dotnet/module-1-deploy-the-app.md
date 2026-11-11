# Module 1 — Deploy the app

**Time:** 25 minutes.

**Goal:** the API and UI running on App Service, and a check that proves your
build is the one serving.

The app is an ASP.NET Core service in `dotnet/services/api` and a React UI in
`apps/web`. It already contains the finished three-agent workflow — that is
what `verify-demo.ps1` exercised in Module 0. This module deploys it to Azure
and proves the build you are looking at is the one serving traffic. Modules 2
and 3 then rebuild that workflow's primitives from scratch, so you know what is
inside it.

## 1. Confirm the hosting exists

```powershell
terraform -chdir=dotnet/infra output api_url
terraform -chdir=dotnet/infra output web_url
```

Both print a URL. Opening either shows the default App Service page, because
nothing is deployed yet.

## 2. Deploy

```powershell
.\dotnet\scripts\deploy-app.ps1
```

The script runs `dotnet publish` for the API and builds the UI bundle on your
machine, zips each app, and pushes each zip with `az webapp deploy`. App
Service builds nothing: the zip it receives is already the compiled app.
Expect a few minutes.

Two details in that script decide whether the deployment works.

**The API zip is the publish output, and it carries the agent definitions.**
The app reads `agents/` from next to its own DLL —
`PromptEnvelope.AgentsDir` is `AppContext.BaseDirectory` plus `agents`. The
API project links the repo's `agents/` folder as content, so `dotnet publish`
copies every `agent.md`, `manifest.yaml` and schema into the output. Zip
anything less and the app starts with no roles to run. App Service runs the
DLL directly, with server-side builds switched off
(`SCM_DO_BUILD_DURING_DEPLOYMENT=false`):

```
dotnet AgenticSupportGuide.Api.dll
```

**The browser never calls the API directly.** It calls `/api` on the web
tier's own origin, and [apps/web/server.js](../../apps/web/server.js) forwards
the call with the shared key attached server-side. A React bundle is
downloadable, so it cannot hold a key; the web tier holds it instead. This is
also why the web tier runs `node server.js` rather than serving static files.

## 3. Confirm your build is serving

The script stamps the API package with a `build_id` and polls `/api/health`
until that value comes back:

```
Waiting for build 20260905-123439-620 to serve ...
  status   = ok
  build_id = 20260905-123439-620
```

A successful deploy does not prove the new code is running. The old worker can
keep answering, so the deploy goes green while your change is nowhere. The
`build_id` is the only signal that settles it.

`/api/health` is the only anonymous route in the API, because this poll runs
before the web tier is up and before anyone holds a key. Everything else,
including `/api/health/details`, requires the key.
`Every_route_requires_the_key_or_is_explicitly_anonymous` in
[dotnet/services/api/AgenticSupportGuide.Api.Tests/AuthTests.cs](../../dotnet/services/api/AgenticSupportGuide.Api.Tests/AuthTests.cs)
fails if a new route is added without it.

## 4. Verify

```powershell
dotnet run dotnet/scripts/smoke_test.cs
```

A health endpoint cannot catch any of these:

| Check | Why it matters |
| --- | --- |
| The web tier proxies `/api` to the deployed API | A UI can load and still call `localhost` |
| The bundle contains no key and no API hostname | Anything in the bundle is public |
| Deep links fall back to `index.html` | `/dashboard` 404s without SPA fallback |
| A real request returns citations | Health checks never call a model |
| Which provider served the evidence | Fixtures and real grounding look identical |
| No cross-dealer-group citations | The isolation claim, actually tested |

Then open the UI and submit a support request.

![The App Service overview blade showing Status Running, Runtime status
Healthy, the B1 App Service plan and the default domain.](../images/module-1-appservice-overview.png)

If a deploy fails, read the log stream:

```powershell
$rg  = terraform -chdir=dotnet/infra output -raw resource_group_name
$app = terraform -chdir=dotnet/infra output -raw api_app_name

az webapp log tail --resource-group $rg --name $app
```

A deploy whose zip is rejected leaves the previous version serving. A deploy
that succeeds and then cannot start takes the site down.

## 5. Check the identity

The deployed API does not run as you. It has a **system-assigned managed
identity**: an Entra identity Azure creates for one resource and destroys
with it. No credential is ever issued to you, which is why this deployment
holds no key or client secret for Foundry.

Open the API App Service → **Settings → Identity**. System assigned is On,
with an object ID that is not yours.

![The App Service Identity blade with System assigned status set to On and an
Object (principal) ID.](../images/module-1-managed-identity.png)

```powershell
$rg  = terraform -chdir=dotnet/infra output -raw resource_group_name
$app = terraform -chdir=dotnet/infra output -raw api_app_name

az webapp identity show --resource-group $rg --name $app --query principalId -o tsv
```

That identity holds three roles:

| Scope | Role | Needed for |
| --- | --- | --- |
| AI Services account | `Cognitive Services OpenAI User` | Direct model calls |
| Foundry project | `Cognitive Services User` | Agent calls |
| Search service | `Search Index Data Reader` | Retrieval |

Account scope and project scope are not redundant. With only the first, the
app starts, `/api/health` reports `ok`, and every agent call fails with
`AGENT_PROVIDER_AUTH_DENIED`. A health check that never calls a model cannot
catch that, which is why `smoke_test.cs` makes a real request.

`Credentials.Default()` builds a `DefaultAzureCredential`, which resolves
to the managed identity in Azure and your `az login` session on your laptop.
Same code in both places. It skips the Visual Studio and VS Code sign-ins,
which would otherwise be tried before `az login` and can hold a different
account than the one with the roles.

## 6. Optional — run the same steps as a pipeline

Skip this unless you want CI.

[.github/workflows/deploy-dotnet.yml](../../.github/workflows/deploy-dotnet.yml) packages,
deploys, confirms the `build_id`, and runs the smoke test. It signs in with
federated credentials, so there is no stored publish profile. It is
`workflow_dispatch` only.

Everything it reads lives on a `workshop-dotnet` environment, so this track's
settings never collide with the Python track's in the same repository. A
fresh fork does not have that environment — create it first, under
**Settings → Environments → New environment**, or every `--env
workshop-dotnet` command below fails.

Set five environment variables:

```powershell
gh variable set AZURE_RESOURCE_GROUP --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw resource_group_name)
gh variable set AZURE_API_APP_NAME   --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw api_app_name)
gh variable set AZURE_WEB_APP_NAME   --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw web_app_name)
gh variable set AZURE_API_URL        --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw api_url)
gh variable set AZURE_WEB_URL        --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw web_url)
```

The post-deploy smoke test calls the API directly, so it needs the key:

```powershell
gh secret set API_SHARED_KEY --env workshop-dotnet `
    --body (terraform -chdir=dotnet/infra output -raw api_shared_key)
```

Create an app registration, grant it **Contributor on the resource group
only**, and store its coordinates in the `workshop-dotnet` environment:

```powershell
az ad app create --display-name gh-asg-deploy
az ad sp create --id <appId>
az role assignment create --assignee-object-id (az ad sp show --id <appId> --query id -o tsv) `
    --assignee-principal-type ServicePrincipal --role Contributor `
    --scope /subscriptions/<sub>/resourceGroups/<rg>

gh secret set AZURE_CLIENT_ID       --env workshop-dotnet --body <appId>
gh secret set AZURE_TENANT_ID       --env workshop-dotnet --body <tenantId>
gh secret set AZURE_SUBSCRIPTION_ID --env workshop-dotnet --body <subscriptionId>
```

The role assignment needs the service principal's *object* ID, which is not
`<appId>` — hence the lookup on the third line. If you already did this for
the Python track, reuse that app registration: grant it Contributor on this
track's resource group too, and add the federated credential below.

Add the federated credential that trusts the repository environment:

```powershell
az ad app federated-credential create --id <appId> --parameters '{
  "name": "gh-workshop-dotnet",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<org>/<repo>:environment:workshop-dotnet",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

> [!NOTE]
> **The subject claim may not be what the documentation says.** On a GitHub
> Enterprise organization it can carry numeric org and repo IDs:
> `repo:<org>@<org-id>/<repo>@<repo-id>:environment:workshop-dotnet`. A
> mismatch fails with `AADSTS700213`. Read the exact subject out of the error
> message and use it verbatim rather than guessing.

```powershell
gh workflow run deploy-dotnet.yml -f component=both -f expect_evidence=fixture
gh run watch --exit-status
```

`expect_evidence=fixture` matches how Terraform starts the app. Note the
spelling: the Terraform variable is `api_evidence_source = "fixtures"`, the
smoke test flag is `--expect-evidence fixture`.

## Check yourself

- [ ] Both URLs serve your application, not the App Service placeholder.
- [ ] `smoke_test.cs` passes every check.
- [ ] You submitted a request through the deployed UI.
- [ ] You can name the API's principal ID and say why it needs three roles.

Next: [Module 2 — Your first agent](module-2-first-agent.md)
