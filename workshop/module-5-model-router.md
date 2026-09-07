# Module 5 — Model router

**Time:** about 45 minutes.

**You will have at the end:** measured evidence of what routing actually does
to your cost and latency — not a vendor claim.

---

## The idea

A model router is a single deployment that decides, per request, which
underlying model should answer. Simple requests go to a small cheap model;
hard ones go to a large one. Your code calls one deployment name and does not
change.

That is genuinely useful. It is also frequently oversold, so this module is
built around measuring it rather than believing it.

## The constraint nobody mentions first

**The router's effective context window is capped by the smallest model
behind it.**

If your router can reach a 128k model and a 16k model, you have a 16k router.
Not sometimes — always, because the router must be able to hand any request
to any model in its set.

This catches people who adopt a router for cost and discover their long-
context prompts now fail. If you have long prompts, check this before
anything else.

Two more worth knowing:

- Non-OpenAI models reachable by the router (Claude, for example) must be
  deployed separately first.
- Failover needs at least two models in the set. A one-model router is just a
  slower deployment.

## 1. Confirm your router deployment

Module 0 created it:

```powershell
terraform -chdir=infra output router_deployment_name
```

In the portal, open **Deployments** → your router. Note the version — each
router version pins the set of models it can route across.

## 2. Make routing visible

Before measuring anything, you need to see which model actually served each
call. The trace carries it.

The coordinator records, per agent step: the provider, **the model that
actually served the call**, latency, and token counts. That model field is
not the deployment name you requested — with a router in front, they differ,
and that difference is the whole point.

Getting this working required one non-obvious thing, worth knowing if you
build your own: in Microsoft Agent Framework, `AgentResponse` has
`usage_details` but **no** model field. The served model lives on the
underlying `ChatResponse`, reachable through `raw_representation`. If you
only read the agent-level response you will never see routing happen.

## 3. Get a baseline

Start the backend in its own terminal (`.\scripts\run-backend.ps1`), then run
the six synthetic cases against it:

```powershell
cd services\api
.\.venv\Scripts\python.exe ..\..\scripts\run_evals.py --live http://127.0.0.1:8000
```

The UI is not the right tool for this: it hardcodes one district and shows
only model and latency, not tokens.

To see a full per-step trace for a single case, call the API directly:

```powershell
$body = @{
  district_id  = "DIST-A"
  learner_id   = "LRN-0001"
  category     = "early-literacy"
  concern_text = "Letter-sound fluency is behind expected pace across two windows."
} | ConvertTo-Json

$r = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/recommendations/support-plan `
  -Method Post -Body $body -ContentType "application/json"

$r.agent_trace | Format-Table agent, status, model, latency_ms, token_estimate -AutoSize
```

A real run looks like this:

```
agent                        status model                   latency_ms token_estimate
-----                        ------ -----                   ---------- --------------
evidence-retrieval           ok     synthetic                        0
data-analyst-agent           ok     gpt-4.1-mini-2025-04-14      13035           1038
support-recommendation-agent ok     gpt-4.1-mini-2025-04-14       7570           2099
validator-agent              passed gpt-4.1-mini-2025-04-14       6203           1598
```

Record, per case:

| Case | Model served | Latency (ms) | Tokens |
| --- | --- | --- | --- |

`token_estimate` is input + output combined. If you need them separately,
`CallMetrics` in
[maf_runtime.py](../services/api/app/foundry_agents/maf_runtime.py) already
carries `input_tokens` and `output_tokens` — the coordinator just sums them.

Write these down. You cannot claim an improvement without them.

## 4. Switch to the router

In `services/api/.env`, point one role at the router deployment that Module 0
created (`FOUNDRY_MODEL_DEPLOYMENT_ROUTER` holds its name):

```
FOUNDRY_MODEL_DEPLOYMENT_ANALYST=asg-router
```

Restart the backend, then re-run exactly the same commands from step 3 and
fill in the same table.

## 5. Now answer the real questions

- Did any case route to a *different* model than another case? If every case
  landed on the same model, the router is doing nothing for your workload.
- Did total tokens go up? Routing adds overhead.
- Did p95 latency change? Routing adds a decision step.
- Did quality change? You cannot answer this yet — that is Module 8. Come
  back and re-run this comparison after you have graders.

## 6. Structured output — check, do not assume

The agents in this repo require strict JSON conforming to the contracts in
`contracts/v1/`. Structured-output support is a property of the *underlying*
model, so a router whose set includes a model with weaker schema adherence
can produce off-contract JSON intermittently.

Test it rather than trusting it. Run all six cases against the router several
times and watch for `invalid_model_json` or `PROTOCOL_VALIDATION_FAILED` in
the trace. Intermittent contract failures under a router — where the plain
deployment was stable — is your answer.

This is also why the coordinator validates every inter-agent message against
a JSON Schema instead of trusting the model. That validation is what turns a
silent data-corruption bug into a visible, attributable failure.

---

## Decision guide

Use a router when:

- Your workload has a genuine mix of easy and hard requests.
- Your prompts fit inside the smallest model's context window.
- You have measured a real cost problem.

Do not use a router when:

- You need long context.
- Your requests are uniformly hard — you will pay routing overhead for nothing.
- You have not measured. "Might be cheaper" is not a reason.

## Check yourself

- [ ] You have a before/after table with real numbers.
- [ ] You can name the model that served at least one specific call.
- [ ] You checked for contract failures under the router.
- [ ] You can state your router's effective context window and why.

Next: [Module 6 — Guardrails](module-6-guardrails.md)
