# Module 10 — Operate what you built

**Time:** 20 minutes.

**You will have at the end:** a trace you can follow from a browser click to
a model call, the queries you would reach for when something is wrong, and a
clear view of what this costs to run.

---

## What you are operating

The same request touches App Service, a knowledge base, and three model
calls. When it is slow, wrong, or more expensive than expected, you need one
story that covers all of it — without redeploying to add a `print`.

Three terms, used throughout:

- **Telemetry** is data the application emits about itself while running:
  events, metrics, and timings. It is something the app chooses to send, not
  something extracted from it.
- **Application Insights** is the Azure service that receives, stores, and
  queries that telemetry. Module 0's Terraform created one and wrote its
  connection string into your `.env`.
- A **trace** here means the ordered set of steps that made up one request.
  This app produces two of them, and they are not the same object. The
  **response trace** is a list of `AgentTraceStep` rows in the API response
  body, which the UI renders. The **spans** are OpenTelemetry records Agent
  Framework emits to Application Insights.

Each has its own identifier. The response trace carries a **correlation ID**,
generated per run and returned on the envelope. The spans carry an
`operation_Id` that OpenTelemetry assigns. Nothing exports the correlation ID
as a span attribute, so you cannot search Application Insights by it.

The coordinator generates the correlation ID in `run`:

```python
state = RunState(
    correlation_id=str(uuid.uuid4()),
    ...
)
```

and it travels on every inter-agent envelope as `trace_id` (see
[services/api/app/workflows/envelopes.py](../services/api/app/workflows/envelopes.py)),
on every audit row, and on the response.

Requests rejected *before* the coordinator runs — a 401, a 404 for an unknown
dealership, or `provider_missing` — have no correlation ID, because there was
no run to correlate. Those show up in App Service logs rather than here.

## 1. Follow a single request end to end

Make a request, then read the trace it returns:

```powershell
$api = terraform -chdir=infra output -raw api_url
$key = terraform -chdir=infra output -raw api_shared_key
$body = @{
    dealer_group_id  = "GROUP-A"
    dealership_id   = "DLR-0001"
    category     = "lead-response"
    concern_text = "First response to online enquiries is slower than the standard."
} | ConvertTo-Json

$r = Invoke-RestMethod "$api/api/recommendations/support-plan" `
    -Method Post -Headers @{ "x-api-key" = $key } `
    -Body $body -ContentType "application/json"

$r.correlation_id
$r.agent_trace | Format-Table agent, status, provider, model, latency_ms
```

The `x-api-key` header is not optional. The API refuses anything that did not
come through the web tier, so without it you get `401` and no trace to follow.
That is the same shared key the UI attaches for you — which is also why the UI
needs no sign-in and anyone with its URL can drive it.

You should see four steps:

| agent | provider | what it did |
| --- | --- | --- |
| `evidence-retrieval` | `foundry_iq` | Retrieved dealer group-scoped evidence |
| `data-analyst-agent` | `azure_foundry_responses` | Interpreted the signals |
| `support-recommendation-agent` | `azure_foundry_responses` | Drafted the plan |
| `validator-agent` | `azure_foundry_responses` | Checked it against the contract |

**Read the `provider` column carefully.** If `evidence-retrieval` says
`fixture`, the app is serving canned evidence and Module 6 did not take
effect. That column was hardcoded during development, so a grounded run and a
fixture run looked identical. It now reports what actually ran, because
`RetrieveEvidence.retrieve` reads it off the retriever instance:

```python
provider = getattr(self._retriever, "provider_name", "unknown")
model = getattr(self._retriever, "provider_model", "unknown")
```

Confirm the same thing from the outside — `/api/health/details` is behind the
same key, so reuse `$key` from the request above:

```powershell
(Invoke-RestMethod "$api/api/health/details" -Headers @{ "x-api-key" = $key }) |
    Select-Object evidence_source, evidence_knowledge_base
```

Only `/api/health` is anonymous, and deliberately so: `deploy-app.ps1` polls
it for the `build_id` before the web tier is up, so it returns a status and a
build id and nothing else.

## 2. Read what the app is allowed to send

Before querying the telemetry, read the code that produces it — which is
almost none, because Agent Framework produces it.
[services/api/app/observability.py](../services/api/app/observability.py) is
the whole integration:

```python
configure_otel_providers(exporters=exporters or None)
enable_instrumentation()
```

From that point Agent Framework emits an OpenTelemetry span for every
workflow run, every executor, every edge delivery and every model call. There
is no event schema in this repo to maintain and no allowlist to keep in sync,
because there is no hand-written recorder.

The privacy property is now a **framework default** rather than a list we
police: `enable_sensitive_data` is False unless you opt in, so prompts and
completions are never attached to a span.

> [!CAUTION]
> Never call `enable_sensitive_telemetry()` here. A workshop runs on a shared
> subscription and a span is forever.

That default is checked, not assumed:
[services/api/tests/test_observability.py](../services/api/tests/test_observability.py)
puts a canary string through a real run and asserts it appears in no span:

```python
assert spans, "no spans captured; this assertion would be vacuous"

for span in spans:
    assert CANARY not in _dump(span), f"user text leaked into span {span.name}"
```

Note the first line. Without it the loop passes on an empty list and proves
nothing — which is exactly what happened the first time this test was
written.

`RuntimeAuditLog` in
[services/api/app/runtime_audit.py](../services/api/app/runtime_audit.py)
is still ours, because it is a product feature rather than telemetry: it
backs `/api/audit/events`. It restricts by construction — `append` takes
named metadata arguments, so an audit row has no field that prompt or
completion text is *supposed* to go in.

`_fetch_audit` in [scripts/run_evals.py](../scripts/run_evals.py) pulls
`/api/audit/events` on a live run, and `score_audit` fails the case if it
finds either a forbidden key name or the case's own concern text anywhere in
the payload:

```python
parts = list(_walk_json(audit_payload))
keys = [text.lower() for kind, text in parts if kind == "key"]
values = " ".join(text.lower() for kind, text in parts if kind == "value")

# An empty audit trail would pass every leak check below vacuously.
if not (audit_payload.get("events") or []):
    _fail(result, "audit payload contains no events")

for unsafe in UNSAFE_AUDIT_KEYS:
    if any(unsafe in key for key in keys):
        _fail(result, f"audit payload exposes '{unsafe}'")
for case in cases:
    concern = str(case["concern_text"]).strip().lower()
    if len(concern) >= AUDIT_CANARY_MIN_CHARS and concern in values:
        _fail(result, f"audit payload contains the concern text of case {case['id']}")
```

Searching for the input text as a canary is the part that matters. Checking
key names alone would pass the same content stored under a name the script
has never heard of.

## 3. Find that request in Application Insights

**KQL** (Kusto Query Language) is the read-only query language Application
Insights uses. A query starts with a table name and pipes rows through
operators. Five cover most of what you need:

| Operator | What it does |
| --- | --- |
| `where` | Keep rows matching a condition |
| `project` | Choose which columns to return |
| `extend` | Add a computed column |
| `summarize` | Aggregate — `count()`, `percentile()`, `avg()` — optionally `by` a column |
| `order by` | Sort |

Agent Framework's spans are all `INTERNAL` or `PRODUCER`, so the Azure Monitor
exporter writes them to the **`dependencies`** table, not `traces`. The span
name is `name`, its duration is `duration`, and its attributes land in
`customDimensions`, which is why the queries below cast out of it.

These are the span names you will see:

| Span | One per |
| --- | --- |
| `workflow.run` | request |
| `workflow.build` | graph construction |
| `executor.process <id>` | node — `data-analyst`, `support-recommender`, `validator`, … |
| `edge_group.process …` | edge delivery, with `edge_group.delivered` |
| `chat` / `invoke_agent` | model call, with `gen_ai.*` token and model attributes |

Do this in the portal the first time. The schema is in front of you,
`customDimensions` is expandable, and the end-to-end transaction view is one
click away — that view matters because the spans are properly
parented and it draws the whole graph as a waterfall.

Open your Application Insights resource `appi-asg-<suffix>` → **Logs**, and
run:

```kusto
dependencies
| where timestamp > ago(1h)
| where name == "workflow.run"
| project timestamp, operation_Id, duration, success
| order by timestamp desc
```

Take the `operation_Id` of your run from that list, then read its whole tree:

```kusto
dependencies
| where timestamp > ago(1h)
| where operation_Id == '<paste operation_Id from above>'
| project timestamp, name, duration, customDimensions
| order by timestamp asc
```

Expand a row and open `customDimensions`. Every attribute the framework
recorded is there — and no prompt text. Check that yourself rather than
taking this page's word for it.

Two more worth saving. The first tells you *what is slow*:

```kusto
// Slowest workflow nodes in the last hour
dependencies
| where timestamp > ago(1h)
| where name startswith "executor.process"
| extend node = tostring(customDimensions["executor.id"])
| summarize p50 = percentile(duration, 50), p95 = percentile(duration, 95) by node
| order by p95 desc
```

p95 rather than an average, because an average hides the slow tail that users
actually notice. Grouping by node is what turns "the app is slow" into "the
recommender is slow", which is a different investigation.

The second tells you *what is broken*:

```kusto
// Failing spans in the last day, grouped by type
dependencies
| where timestamp > ago(24h)
| where success == false
| extend node = tostring(customDimensions["executor.id"]),
         error = tostring(customDimensions["error.type"])
| summarize count() by node, error
```

Because a failing step raises rather than returning a status, the exception
propagates through the span and `success` is false without anything having to
remember to record it.

The same query from a shell, for scripting or for an alert rule:

```powershell
$ai = terraform -chdir=infra output -raw application_insights_name
$rg = terraform -chdir=infra output -raw resource_group_name
az monitor app-insights query -g $rg -a $ai --analytics-query @"
dependencies | where timestamp > ago(1h) | summarize count() by name
"@
```

**Use single quotes inside a query you pass to the CLI.** The queries above
are written for the portal editor, where `"executor.id"` is fine. Moving one
to `--analytics-query` unchanged fails with an unhelpful
`BadArgumentError: The request had some invalid properties`, because the
embedded double quotes do not survive the shell. Swap them:

```powershell
az monitor app-insights query -g $rg -a $ai --analytics-query `
  "dependencies | where timestamp > ago(1h) | where name startswith 'executor.process' | extend node = tostring(customDimensions['executor.id']) | summarize n = count() by node"
```

KQL accepts either quote character, so this is the same query. The error
names neither the clause nor the cause, so it is worth recognising on sight.

## 4. Stream logs while something is wrong

**Log stream** attaches to the running worker's stdout and stderr. It shows
you what the process is printing right now, with no ingestion delay.

In the portal: your API App Service → **Monitoring → Log stream**.

Leave it open and make a request. This is the fastest way to see an import
error or a startup failure, neither of which reaches Application Insights —
the process never got far enough to send anything.

The same stream attached to your terminal, which is what you want when you
are watching a deploy land and do not want to be clicking:

```powershell
$rg  = terraform -chdir=infra output -raw resource_group_name
$app = terraform -chdir=infra output -raw api_app_name
az webapp log tail -g $rg -n $app
```

## 5. What a failed start looks like

Two failure shapes behave very differently. A build that fails never reaches
startup, so the previously deployed code keeps serving. A build that succeeds
and then fails to **start** takes the site down, and App Service spends ten
minutes finding out:

```
Status: Site failed to start. Time: 610(s)
ERROR: Deployment failed because the site failed to start within 10 mins.
InprogressInstances: 0, SuccessfulInstances: 0, FailedInstances: 1
```

Health then returns **HTTP 503**, and the browser shows the platform's error
page rather than one of yours:

![A browser showing the App Service 503 Service Unavailable page, which says
the server is unable to handle the request right now and offers a Try again
button.](images/module-10-site-down-503.png)

A 500 means your code ran and failed. A 503 from the platform means there is
no healthy worker. This app also returns its own 503 when `API_SHARED_KEY` is
missing — a JSON `detail` body is the application, the branded page is not.

**Do not expect a Python traceback.** The platform reports its own view:

```
ContainerStartupFailure ... Container exited with exit code 1 during startup
Site startup probe failed after 7.4 seconds.
```

The `ModuleNotFoundError` went to the container's stderr, and in a downloaded
bundle the `containerStream` file for the failed instance was empty — the
worker died before the log pipeline shipped anything. To see the traceback you
generally have to be attached to the live stream when it crashes. For the same
reason nothing reached Application Insights: the SDK never initialised.

| Failure | What you see | What catches it |
| --- | --- | --- |
| App cannot start | Deploy fails after 10 min; site down | Health never returns the new `build_id` |
| App starts, old code serves | Deploy succeeds; behaviour unchanged | `build_id` check in the script |

The second is the one that wastes a day, and it is why `deploy-app.ps1`
stamps a `build_id` and polls for it.

`az webapp deploy` is unreliable in both directions, and both were observed
here: exit 0 with the old worker still answering, and exit 1 with the new
build live and healthy. The script treats a non-zero exit as a warning and
lets the `build_id` decide. One authoritative signal beats two ambiguous ones.

A failed start plus a recovery deploy is over fifteen minutes of downtime for
a one-line mistake. That is the argument for
[deployment slots](https://learn.microsoft.com/azure/app-service/deploy-staging-slots):

```powershell
# What this workshop does NOT do, and production should
az webapp deployment slot create -g $rg -n $app --slot staging
az webapp deploy -g $rg -n $app --slot staging --src-path api.zip --type zip
.\services\api\.venv\Scripts\python.exe scripts\smoke_test.py --api-url "https://$app-staging.azurewebsites.net"
az webapp deployment slot swap -g $rg -n $app --slot staging
```

Slots need **Standard or higher** and this workshop provisions B1, so the
first command fails on your plan. That is the lesson: the cheapest tier is the
one without the feature that prevents outages. With a slot, a broken build
fails to start in staging and production keeps serving. Rollback becomes a
second swap, and does not depend on a build succeeding.

## 6. Know what it costs

Open **Cost Management → Cost analysis** on your resource group. It breaks
the bill down by service, location and resource, which is the view that
answers "what is actually costing me money" — and the answer is usually not
the thing you expected:

![Cost analysis for the workshop resource group showing actual cost of $32.51
against a $108.93 forecast, with Azure Cognitive Search at $18.48, Microsoft
Defender at $8.85, Bing Services at $2.58 and App Service at
$1.30.](images/module-10-cost-analysis.png)

Group by **Service name**, then by **Resource**, and find the single most
expensive thing in your environment before you read the table below.

A rougher view from a shell — subscription-wide and not date-bounded the same
way, so the totals will not match what you just read:

```powershell
az consumption usage list --top 20 -o table
```

Measured on a real workshop resource group over a partial month:

| Service | Measured | Why |
| --- | --- | --- |
| Azure AI Search `basic` | $18.48 | Per hour, always on. The single biggest cost |
| Microsoft Defender for Cloud | $8.85 | Already enabled at subscription level in many tenants |
| Bing Services | $2.58 | Module 6's web knowledge source bills per query |
| App Service Plan × 2 | $1.30 | Per hour, and low here only because the plans were briefly on the free tier |
| Foundry models | $0.40 | Per token |

**Two of those are not on anyone's mental model of this workshop.** Nobody
chose Defender for Cloud, and nobody thinks of a knowledge base as something
that incurs Bing Services charges. Grounding has a bill attached, and it is
not the model tokens — those were the *smallest* line at forty cents.

That Search line is for `basic`, at $0.10 per hour. If `basic` had no
capacity when you provisioned and you fell back to `standard`, you are paying
$0.34 per hour for the same row — about 3.4 times more. Check which tier you
actually got; it is the largest number on the bill either way.

The two App Service plans and the Search service bill whether or not anyone
uses them. When you are finished with the **whole** workshop — including the
optional section below, which needs the resources to still exist:

```powershell
terraform -chdir=infra destroy
```

Expect this to take a while. Some resources — Foundry projects especially —
soft-delete rather than disappear, which is why every name in this repo
carries a random suffix.

## 7. Optional — turn a query into an alert

**Skip this if you are not doing operations work.** Nothing later depends on
it; this is the last module.

Section 5 described a failed start that took ten minutes to be declared dead.
Nothing would have told you — that is the gap an alert closes, and you now
have the queries to build one.

In the portal: your Application Insights resource → **Alerts** → **Create →
Alert rule**. Use a **Custom log search** condition and paste the failure
query from section 3:

```kusto
dependencies
| where timestamp > ago(15m)
| where success == false
| summarize failures = count()
```

Fire when `failures` is greater than zero, evaluated every five minutes.

Two decisions matter more than the query:

- **Alert on symptoms users feel, not on causes.** "Requests are failing" is
  actionable. "CPU is high" is not, and pages people at night for nothing.
- **An alert nobody acts on trains people to ignore alerts.** If you would
  not get out of bed for it, make it a dashboard instead.

A crash before startup would not have fired this rule, which is
worth noting: the app never starts, so it logs nothing. Availability
needs a check from *outside* — an availability test against `/api/health` —
not a query over telemetry the dead process could not send.

---

## Check yourself

- [ ] Traced one request across retrieval and three agent calls
- [ ] Found that request in Application Insights by `operation_Id`
- [ ] Can explain the difference between a 500 and a 503 from App Service
- [ ] Can explain why a staging slot prevents a failed-start outage
- [ ] Can name what this environment costs while idle

## You have finished

Back to the [workshop index](README.md), or tear it all down with
`terraform -chdir=infra destroy`.
