# Module 7 — Model router

**Time:** 20 minutes.

**You will have at the end:** measured evidence of what routing actually does
to your cost and latency — not a vendor claim.

---

## What a model router is

A model router is a single deployment that decides, per request, which
underlying model should answer. Simple requests go to a small cheap model;
hard ones go to a large one. Your code calls one deployment name and does not
change.

The claim is lower cost at the same quality. This module is built around
measuring that on your own workload rather than accepting it.

## Context-window limit

**The router's effective context window is capped by the smallest model
behind it.**

A context window is the maximum number of tokens a model can hold at once —
your instructions, the retrieved evidence, the conversation, and the answer
it is generating, all together. Exceed it and the call fails.

If your router can reach a 128k model and a 16k model, you have a 16k router.
Not sometimes — always, because the router must be able to hand any request
to any model in its set.

This catches people who adopt a router for cost and discover their
long-context prompts now fail. If you have long prompts, check this first.

Two more worth knowing:

- Non-OpenAI models reachable by the router (Claude, for example) must be
  deployed separately first.
- Failover needs at least two models in the set. A one-model router is just a
  slower deployment.

## 1. Confirm your router deployment

A *deployment* is a named, quota-bearing instance of a model in your Foundry
project. Your code never names a model; it names a deployment, which is what
makes swapping the model behind it a configuration change.

Module 0 created one for the router:

```powershell
terraform -chdir=infra output router_deployment_name
```

In the portal, open **Build → Models → Deployments** → your router. Note the
version — each router version pins the set of models it can route across.

![The asg-router deployment Details tab showing deployment type
GlobalStandard, model name model-router, model version 2025-11-18, a tokens
per minute rate limit, and Key showing "API Key authentication is
disabled".](images/module-7-router-deployment.png)

Two things on that page matter more than the version. The rate limit is the
capacity you set in Module 0, in thousands of tokens per minute — it is what
your requests queue behind under load. And **API key authentication is
disabled**: every call in this workshop is Entra-authenticated, so there is
no key to leak.

## 2. Read the code that makes routing visible

You cannot measure routing you cannot see. The served model reaches the trace
through two functions in
[services/api/app/foundry_agents/maf_client.py](../services/api/app/foundry_agents/maf_client.py).

```python
def _served_model(response: Any) -> str:
    """`AgentResponse` has no model field; the underlying `ChatResponse` does."""

    raw = getattr(response, "raw_representation", None)
    for candidate in (response, raw):
        model = getattr(candidate, "model", None)
        if isinstance(model, str) and model:
            return model
    return ""
```

This is the non-obvious part of building your own. In Microsoft Agent
Framework, `AgentResponse` carries `usage_details` but no model field. The
model that actually served the call is on the underlying `ChatResponse`,
reachable through `raw_representation`. Read only the agent-level response
and you will never see routing happen.

Token counts have their own trap:

```python
def _usage(response: Any, key: str) -> int | None:
    """`usage_details` is a mapping, not an object - getattr silently misses."""

    usage = getattr(response, "usage_details", None)
    if usage is None:
        raw = getattr(response, "raw_representation", None)
        usage = getattr(raw, "usage_details", None)
    if isinstance(usage, Mapping):
        value = usage.get(key)
        return value if isinstance(value, int) else None
    value = getattr(usage, key, None)
    return value if isinstance(value, int) else None
```

`getattr(usage, "input_token_count", None)` on a mapping returns `None`
without raising. Every call would have reported zero tokens and nothing would
have looked broken.

Both feed a `CallMetrics` record. `collect_call_metrics` in
[services/api/app/foundry_agents/maf_runtime.py](../services/api/app/foundry_agents/maf_runtime.py)
is a context manager the coordinator opens for the whole request, so every
call made anywhere inside lands in one list. `RunState.drain_calls` then takes
the calls belonging to the step that just finished:

```python
def drain_calls(self, start: int) -> tuple[str, int | None]:
    """Model that served the newest calls, and their total token count."""
```

That is how one trace row gets the right model and the right token count
without every agent having to report them itself.

## 3. Get a baseline

Start the backend in its own terminal (`.\scripts\run-backend.ps1`).

Two different things are worth measuring, and one command does not do both.

`run_evals.py --live` posts each case in
[evals/synthetic_cases.jsonl](../evals/synthetic_cases.jsonl) to a running API
and scores the envelope it gets back. It answers *did routing break the
contract*, and it prints pass or fail per case — **not** model, latency or
tokens:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\run_evals.py --live http://127.0.0.1:8000
```

The per-step numbers come from calling the API directly. The UI is not the
right tool: it shows model and latency but not tokens.

Run this **three times**, changing `category` each time to `lead-response`,
`listing-completeness` and `inventory-ageing`. Three cases is enough to see
whether the router picks different models for different work, and keeps this
module inside its 20 minutes:

```powershell
$body = @{
  dealer_group_id  = "GROUP-A"
  dealership_id   = "DLR-0001"
  category     = "lead-response"
  concern_text = "Median first response to online enquiries has slipped past one hour."
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

`evidence-retrieval` shows `synthetic` and zero latency because it made no
model call — `step.trace_local` records it so the trace shows the whole
workflow, not only the parts that cost money.

Record, for each of the three cases:

| Case | Model served | Latency (ms) | Tokens |
| --- | --- | --- | --- |
| lead-response | | | |
| listing-completeness | | | |
| inventory-ageing | | | |

`token_estimate` is input + output combined. If you need them separately,
`CallMetrics` already carries `input_tokens` and `output_tokens`; the
coordinator sums them.

Write these down. You cannot claim an improvement without them.

## 4. Switch to the router

Each role reads its own deployment name from an environment variable — see
`load_role_definitions` in
[services/api/app/foundry_agents/role_definitions.py](../services/api/app/foundry_agents/role_definitions.py),
which pairs each `agent.md` with the variable named in its `manifest.yaml`.
Pointing one role at the router is a one-line change, and no agent code moves.

In `services/api/.env`, set the analyst's deployment to the router that
Module 0 created (`FOUNDRY_MODEL_DEPLOYMENT_ROUTER` holds its name):

```
FOUNDRY_MODEL_DEPLOYMENT_ANALYST=asg-router
```

Restart the backend, then re-run exactly the same three calls from step 3 and
fill in a second copy of the same table.

**Put the original value back before you move on.** Restore
`FOUNDRY_MODEL_DEPLOYMENT_ANALYST=asg-chat` and restart the backend — later
modules assume the analyst is on `asg-chat`. Keep the router only if your own
numbers argued for it, and then expect those modules to read differently.

## 5. Now answer the real questions

- Did any case route to a *different* model than another case? If all three
  landed on the same model, the router is doing nothing for this workload.
- Did total tokens go up? Routing adds overhead.
- Did latency change? Routing adds a decision step. Three cases is a
  direction, not a distribution — do not quote a percentile from it.
- Did quality change? Not from this run. A graded harness
  evaluates the **support explainer**, not the analyst you just rerouted, so
  it cannot answer this. Judging routing quality means grading the workflow's
  own output against the same cases before and after — worth doing, and not
  something this workshop automates.

## 6. Structured output — check, do not assume

*Structured output* is a model feature: the service constrains generation so
the response conforms to a JSON schema you supply, instead of asking for JSON
in the prompt and hoping. The agents in this repo depend on it — every
inter-agent message must match a contract in `contracts/v1/`.

Support is a property of the *underlying* model, not of the router. A router
whose set includes a model with weaker schema adherence can produce
off-contract JSON intermittently.

Test it rather than trusting it. Run the six cases once against the router and
watch for `invalid_model_json` or `PROTOCOL_VALIDATION_FAILED`:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\run_evals.py --live http://127.0.0.1:8000
```

This is the contract check from step 3, now pointed at the router. A failure
here that did not happen on the plain deployment is your answer. Intermittent
failures are the harder case: if you suspect one, repeat the run rather than
concluding from a single pass.

This is what the schema validation in Module 3 buys. Without
it, a weaker model behind a router silently corrupts data. With it, the same
event is a named, attributable failure in the trace.

---

## 7. Optional — keep the measurement as a record

**Skip this if you are not doing FinOps or capacity work.** Nothing later
depends on it.

The before-and-after numbers you just took are the whole basis for a routing
decision, and they have a shelf life. Model versions change, prices change,
and the router's own version picks up new models over time. A number in
someone's notebook is not evidence six months later.

The habit worth forming is to record, for each comparison:

| Field | Why it matters |
| --- | --- |
| Date, and the router deployment's model version | The routing set is not fixed forever |
| Which model actually served each case | "The router is cheaper" means nothing without this |
| Total tokens per case | Cost is per token. The trace sums input and output, so for per-token pricing you need the provider's own usage data |
| Latency per case | The trade you are actually making |
| The case set | Two runs over different questions are not comparable |

Most of that is already in the trace your API returns — `provider`, `model`,
`latency_ms` and `token_estimate` per step — so it is mostly a matter of
keeping the output rather than gathering new data. The exception is the
input/output token split: `token_estimate` is their sum, which is enough to
compare totals but not to price a run where input and output cost different
amounts.

Two cautions. Measure over the same fixed cases both times, or you are
comparing questions rather than routers. And do not put a live
model-comparison run on every commit: it costs real tokens and it is
non-deterministic.

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

Next: [Module 8 — Guardrails](module-8-guardrails.md)
