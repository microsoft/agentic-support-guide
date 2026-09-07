# Module 9 — Operate what you built

**Time:** about 75 minutes, roughly 20 of which is waiting for a broken
deployment to be declared dead and then recovering from it. That wait is
deliberate.

**You will have at the end:** a trace you can follow from a browser click to
a model call, a real outage you caused and recovered from, and a clear view
of what this costs to run.

---

## Why this module exists

Modules 0 through 8 got you to a working, measured, guarded system. This one
is about the part nobody demos: the Tuesday afternoon when something is
slow, or wrong, or more expensive than expected, and you have to find out
why without redeploying.

DevOps and GenAIOps converge here. The same request touches App Service, a
knowledge base, and three model calls. You need one story that covers all of
it.

## 1. Follow a single request end to end

Make a request through the UI, then pull the trace for it:

```powershell
$api = terraform -chdir=infra output -raw api_url
$body = @{
    district_id  = "DIST-A"
    learner_id   = "LRN-0001"
    category     = "early-literacy"
    concern_text = "Letter-sound fluency below expected pace."
} | ConvertTo-Json

$r = Invoke-RestMethod "$api/api/recommendations/support-plan" `
    -Method Post -Body $body -ContentType "application/json"

$r.correlation_id
$r.agent_trace | Format-Table agent, status, provider, model, latency_ms
```

You should see four steps:

| agent | provider | what it did |
| --- | --- | --- |
| `evidence-retrieval` | `foundry_iq` | Retrieved district-scoped evidence |
| `data-analyst-agent` | `azure_foundry_responses` | Interpreted the signals |
| `support-recommendation-agent` | `azure_foundry_responses` | Drafted the plan |
| `validator-agent` | `azure_foundry_responses` | Checked it against the contract |

**Read the `provider` column carefully.** If `evidence-retrieval` says
`fixture`, the app is serving canned evidence and Module 3 did not take
effect. That column was hardcoded during development, which meant a grounded
run and a fixture run looked identical — the sort of bug that turns a demo
into a false claim. It now reports what actually ran.

Confirm the same thing from the outside:

```powershell
(Invoke-RestMethod "$api/api/health/details") |
    Select-Object evidence_source, evidence_knowledge_base
```

## 2. Find that request in Application Insights

The `correlation_id` from step 1 ties the API span to the agent calls.

```powershell
$ai = terraform -chdir=infra output -raw application_insights_name
$rg = terraform -chdir=infra output -raw resource_group_name
az monitor app-insights query -g $rg -a $ai --analytics-query @"
traces
| where timestamp > ago(1h)
| where customDimensions.correlation_id == '<paste correlation_id>'
| project timestamp, message, customDimensions
| order by timestamp asc
"@
```

Useful queries to keep:

```kusto
// Slowest agent steps in the last hour
traces
| where timestamp > ago(1h)
| where isnotempty(customDimensions.latency_ms)
| extend agent = tostring(customDimensions.agent),
         latency = toint(customDimensions.latency_ms)
| summarize p50 = percentile(latency, 50), p95 = percentile(latency, 95) by agent
| order by p95 desc
```

```kusto
// Requests that failed, and why
traces
| where timestamp > ago(24h)
| where customDimensions.status !in ("ok", "passed")
| summarize count() by tostring(customDimensions.status),
                       tostring(customDimensions.code)
```

Nothing here reads student text. Only identifiers, statuses, and timings are
recorded — see [security-and-privacy.md](../docs/security-and-privacy.md).

## 3. Stream logs while something is wrong

```powershell
$rg  = terraform -chdir=infra output -raw resource_group_name
$app = terraform -chdir=infra output -raw api_app_name
az webapp log tail -g $rg -n $app
```

Leave that running and make a request. This is the fastest way to see an
import error or a startup failure, neither of which reaches Application
Insights, because the process never got far enough to report anything.

## 4. Break the running app on purpose

Module 1 broke the *build* — the package never installed, so the old code
kept serving. This is the other failure: the build succeeds, and the app
then fails to **start**. It is far worse, and this is the module where you
feel why.

Note the build that is currently live:

```powershell
(Invoke-RestMethod "$api/api/health").build_id
```

Now introduce a real failure. Add a bad import at the top of
`services/api/app/main.py`:

```python
import this_module_does_not_exist
```

Deploy it:

```powershell
.\scripts\deploy-app.ps1 -Only api
```

**Go and do something else for ten minutes.** That wait is part of the
lesson. Here is what actually happens, measured:

```
Status: Starting the site... Time: 578(s)
Status: Starting the site... Time: 594(s)
Status: Site failed to start. Time: 610(s)
ERROR: Deployment failed because the site failed to start within 10 mins.
InprogressInstances: 0, SuccessfulInstances: 0, FailedInstances: 1
```

Then check health:

```powershell
Invoke-RestMethod "$api/api/health" -TimeoutSec 30
```

It times out. **The site is down.**

This is the part worth sitting with. A single-instance App Service with no
staging slot has no rollback: the platform replaced a working deployment
with a broken one, spent ten minutes discovering it could not start, and
left you with an outage. Nothing "fell back" to the previous build. The
previous build is gone.

Confirm the cause in the logs:

```powershell
az webapp log tail -g $rg -n $app
```

You will see the `ModuleNotFoundError` — the worker never got far enough to
serve anything, which is also why nothing about this reached Application
Insights. A crash before startup is invisible to the telemetry you
configured in Module 0.

### Two different failures, two different detections

| Failure | What you see | What catches it |
| --- | --- | --- |
| App cannot start | Deploy fails after 10 min; site down | Health never returns the new `build_id` |
| App starts, but old code serves | Deploy succeeds; behaviour unchanged | `build_id` check in the script |

The second is the sneaky one, and it is why `deploy-app.ps1` stamps a
`build_id` and polls for it. A deploy that reports success while the
previous worker keeps answering looks exactly like a healthy deploy. During
development this cost an hour of debugging a fix that had already shipped —
the code was correct and simply was not running.

### The deploy command's exit code is not the truth

Notice what `deploy-app.ps1` does **not** do: it does not fail just because
`az webapp deploy` returned non-zero. That command is unreliable in both
directions, and both were observed while building this workshop:

- **Exit 0, wrong code serving.** Oryx skipped the rebuild and the old
  worker kept answering.
- **Exit 1, correct code serving.** `az` gives up waiting after 10 minutes.
  The recovery deploy in the next step took longer than that to cold-start,
  so `az` reported failure — and the new build was live and healthy anyway.

If the script trusted that exit code, the second case would send you
debugging a deployment that had already succeeded. So the script treats a
non-zero exit as a warning and lets the `build_id` decide. **One
authoritative signal beats two ambiguous ones.**

## 5. Recover

Remove the bad import and redeploy:

```powershell
.\scripts\deploy-app.ps1 -Only api
python scripts\smoke_test.py --expect-evidence foundry_iq
```

Time this. It is another full build and cold start — several more minutes of
downtime on top of the ten you already spent. Your total outage for a
one-line mistake is comfortably over fifteen minutes.

That number is the entire argument for
[deployment slots](https://learn.microsoft.com/azure/app-service/deploy-staging-slots),
and it lands far better after you have waited through it:

```powershell
# What this workshop does NOT do, and production should
az webapp deployment slot create -g $rg -n $app --slot staging
az webapp deploy -g $rg -n $app --slot staging --src-path api.zip --type zip
python scripts\smoke_test.py --api-url "https://$app-staging.azurewebsites.net"
az webapp deployment slot swap -g $rg -n $app --slot staging
```

With a slot, the broken build never takes traffic. It fails to start in
`staging`, the smoke test fails there, and production keeps serving the
whole time. Rollback becomes a second swap — instant, and it does not depend
on a build succeeding.

**That is the rule worth taking away: rollback must not require a build.**
This workshop deploys straight to production so you can feel why that is a
bad idea.

## 6. Know what it costs

```powershell
az consumption usage list --top 20 -o table
```

Standing costs for this workshop environment:

| Resource | SKU | Roughly |
| --- | --- | --- |
| App Service Plan × 2 | B1 Linux | Per-hour, always on |
| Azure AI Search | basic | Per-hour, always on |
| AI Services | pay-per-token | Per request |
| Storage, Log Analytics | consumption | Negligible here |

The two App Service Plans and the Search service bill whether or not anyone
uses them. When you are done:

```powershell
terraform -chdir=infra destroy
```

Expect this to take a while. Some resources — Foundry projects especially —
soft-delete rather than disappear, which is why every name in this repo
carries a random suffix.

## 7. What to watch in a real deployment

| Signal | Where | Why it matters |
| --- | --- | --- |
| `build_id` on `/api/health` | Health endpoint | Catches stale deploys |
| `evidence_source` | `/api/health/details` | Catches ungrounded answers |
| `provider` per trace step | Response body | Catches a silent fixture fallback |
| p95 latency by agent | App Insights | Which agent is the bottleneck |
| Validator rejection rate | App Insights | Quality drift after a prompt change |
| Guardrail block counts | Module 6 | Attack surface, and false positives |
| Token spend by deployment | Cost analysis | The bill nobody forecasts |

---

## Checkpoint

- [ ] Traced one request across retrieval and three agent calls
- [ ] Found that request in Application Insights by `correlation_id`
- [ ] Broke the deployment and watched the site go down for ten minutes
- [ ] Recovered, and timed the total outage
- [ ] Can explain why a staging slot would have prevented all of it
- [ ] Can name what this environment costs while idle

## What you should be able to explain

- Why a crash before startup never reaches Application Insights.
- The difference between a deploy that fails and a deploy that silently
  serves stale code, and what detects each.
- Why rollback must not depend on a build succeeding.
- Which single signal tells you whether an answer was grounded.

## You have finished

Back to the [workshop index](README.md), or tear it all down with
`terraform -chdir=infra destroy`.
