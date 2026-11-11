# Module 3 — Workflows

**Time:** 35 minutes.

**Goal:** a running three-agent workflow, and the ability to point at the
lines that make each of its guarantees hold.

Agent Framework gives you three words, and this module is only about them:

| Term | What it is |
| --- | --- |
| **Executor** | A step. It receives input, does work, emits output. |
| **Edge** | A connection that routes a value from one executor to the next. |
| **Workflow** | The graph they form, built with `WorkflowBuilder`. |

That is the whole model. Microsoft Learn covers each in depth —
[workflow concepts](https://learn.microsoft.com/agent-framework/concepts/workflows/),
[executors](https://learn.microsoft.com/agent-framework/concepts/workflows/executors),
and [edges](https://learn.microsoft.com/agent-framework/concepts/workflows/edges)
— and this module builds one, then shows you the same graph running the app.

## Before you start

Sections 5, 9 and 10 change a line and submit a request, so start the app now
and leave it running. `run-backend.ps1` starts uvicorn against `python/services/api`
with `python/services/api/.env` loaded. `run-frontend.ps1` starts the Vite dev server,
which proxies `/api` to the backend. Both block, so use two terminals.

```powershell
# Terminal 1
.\python\scripts\run-backend.ps1
```

```powershell
# Terminal 2
.\python\scripts\run-frontend.ps1
```

If the backend fails to bind port 8000, it is already running from Module 0 —
keep that terminal and start only the frontend.

Open <http://127.0.0.1:5173>. Section 9 comes back to what a request does once
it arrives.

## 1. The smallest workflow

Run [code/05_first_workflow.py](code/05_first_workflow.py). No model, no
Azure, no network — three plain Python steps joined by two edges:

<!-- sample-05:start -->
```mermaid
flowchart TD
  normalise["normalise (Start)"];
  classify["classify"];
  summarise["summarise"];
  normalise --> classify;
  classify --> summarise;
```
<!-- sample-05:end -->

Those three words are the whole model:

- an **executor** is a step — a class with an `@handler` or a function with
  `@executor`;
- an **edge** joins two, and the target runs when the source sends a message;
- a **workflow** is `WorkflowBuilder(start_executor=...).add_edge(...).build()`.

Run [code/06_agents_in_a_workflow.py](code/06_agents_in_a_workflow.py), which
swaps two plain steps for agents. That is **sequential orchestration**.

Now run [code/07_conditional_repair.py](code/07_conditional_repair.py), which
adds the one branch this application uses:

<!-- sample-07:start -->
```mermaid
flowchart TD
  retrieve["retrieve (Start)"];
  recommend["recommend"];
  validate["validate"];
  accept["accept"];
  give_up["give_up"];
  retrieve --> recommend;
  recommend --> validate;
  validate -. conditional .-> accept;
  validate -. conditional .-> recommend;
  validate -. conditional .-> give_up;
```
<!-- sample-07:end -->

Both diagrams are generated, not drawn: `render_workflow_diagram.py` builds
the workflow and calls `WorkflowViz(...).to_mermaid()`, and a test fails if
what is committed drifts from what the code produces.

`WorkflowViz` also writes Graphviz DOT. The app's graph is committed as
`apps/web/public/workflow-graph.svg`, which the app shows under **Workflow
graph** at the foot of the agent panel on the Supports page, so the picture a
learner sees in the running UI comes from the same `build_plan_workflow` the
request uses. `--dot` prints that graph; Graphviz turns it into the SVG:

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\render_workflow_diagram.py --dot | dot -Tsvg -o apps\web\public\workflow-graph.svg
```

That needs Graphviz installed. The SVG is committed for exactly that reason —
App Service has no `dot`.

The pattern is **sequential orchestration with one conditional repair edge** —
not handoff, concurrent, group chat or magentic.
[docs/orchestration-patterns.md](../../docs/orchestration-patterns.md) covers the
others. The order is fixed; the only branch is the validator's verdict, and
Python decides it, not a model.

## 2. The app is the same graph

Three agents run in order, each needing the previous one's output:

| Agent | Input | Output |
| --- | --- | --- |
| Data Analyst | scores and operations history for one dealership | findings |
| Support Recommender | findings + allowed catalogs + retrieved evidence | a draft plan |
| Validator | the draft + the analyst findings | pass/fail + repair guidance |

The analyst sits between `retrieve` and `recommend`, outside the repair loop:
a rejected draft is the recommender's problem, so re-running the analysis
would cost a model call and change nothing.

Open [python/services/api/app/workflows/graph.py](../../python/services/api/app/workflows/graph.py).
The entire orchestration is one expression:

```python
workflow = (
    WorkflowBuilder(
        start_executor=retrieve,
        name="support-plan",
        description="Sequential orchestration with one conditional repair edge.",
        # Only these two produce the run's result. Naming them keeps a
        # future yield from joining it.
        output_from=[finalise, refuse],
        # The working nodes yield their trace rows; these arrive on the
        # event stream as intermediate outputs, never as the result.
        intermediate_output_from=[retrieve, analyse, recommend, validate],
    )
    .add_edge(retrieve, analyse)
    .add_edge(analyse, recommend)
    .add_edge(recommend, validate)
    .add_edge(validate, finalise, condition=passed)
    .add_edge(validate, recommend, condition=needs_repair)
    .add_edge(validate, refuse, condition=repair_exhausted)
    .build()
)
```

Six edges. The three conditional ones are the validator's verdict: pass,
repair once, or give up.

Two details are load-bearing.

**`output_from` and `intermediate_output_from`.** Every node calls
`ctx.yield_output`, but not for the same reason. The two terminal nodes yield
the run's result; the four working nodes yield one trace row each. Naming
them separately is what keeps a trace row out of the result: if a later node
started yielding, its payload would not quietly join the result
`_single_result` expects to be exactly one.

**The workflow is built per request, never cached.** A `Workflow` instance
refuses a second concurrent run with `WorkflowException: Workflow is already
running`, and these nodes hold one request's identity.

## 3. The message that travels the edges

An edge routes a value. Here that value is one frozen dataclass, in
[python/services/api/app/workflows/plan.py](../../python/services/api/app/workflows/plan.py):

```python
@dataclass(frozen=True)
class PlanState:
    concern: str
    evidence: EvidenceBundle | None = None
    analysis: DataAnalystOutput | None = None
    draft: SupportRecommendationDraft | None = None
    report: ValidatorReport | None = None
    attempts: int = 0
    evidence_count: int | None = None
    citation_count: int | None = None
    citations_proposed: int | None = None
    citations_accepted: int | None = None
    validation_reached: bool = False
    deterministic_checks_total: int | None = None
```

Each executor fills in one more field and passes it on with `with_()`, which
is `dataclasses.replace`. The counters at the bottom are the receipt the UI
shows. `None` means the stage never ran; a zero would claim it ran and found
nothing.

> [!IMPORTANT]
> `frozen=True` is not a style preference. A node's outgoing edges share
> **one** message object and each condition is evaluated against it. When an
> earlier version mutated the state in place, the already-scheduled `passed`
> condition re-read the mutated object, saw a clean report, and fired too —
> one run, two outputs. A frozen dataclass makes that impossible.
> [test_sample_workflows.py](../../python/services/api/tests/test_sample_workflows.py)
> reproduces it.

The three edge conditions are plain functions in the same file:

```python
def passed(state: PlanState) -> bool:
    return state.report is not None and state.report.passed


def needs_repair(state: PlanState) -> bool:
    return (
        state.report is not None
        and not state.report.passed
        and state.attempts < MAX_RECOMMENDER_ATTEMPTS
    )
```

`repair_exhausted` is the same shape with `>=`. No model decides the route.

Two more properties fall out of the graph shape:

- **Evidence is retrieved by the first executor**, not offered to the analyst
  as a tool it may call. If retrieval returns nothing the run stops with
  `evidence_missing` and no model is invoked at all.
- **No executor checks whether the previous one worked.** A failed step
  raises `StepFailed` carrying its status and the `PlanState` so far, which
  propagates out of `workflow.run()` so the coordinator catches it in one
  place. That is why the graph reads as six edges and nothing else.

## 4. Inside one executor

Every executor does the same three things around its agent call. `Recommend`
in [python/services/api/app/workflows/executors.py](../../python/services/api/app/workflows/executors.py)
is representative:

```python
result = await _call_agent(
    ctx,
    self._run,
    plan,
    agent_name,
    lambda: self._agent.recommend_with_counts(
        plan.require_analysis(), context, repair_guidance=guidance
    ),
)
await ctx.yield_output(
    StepRecord(
        agent=agent_name,
        status="ok",
        provider=PROVIDER_ID,
        model=_model_of(result.call),
        token_estimate=_tokens_of(result.call),
    )
)
await ctx.send_message(
    plan.with_(
        draft=result.draft,
        attempts=attempts,
        citation_count=len(result.draft.citations),
        citations_proposed=result.citations_proposed,
        citations_accepted=result.citations_accepted,
    )
)
```

The last two counters are why the app can say *"the model proposed three
citation ids and two matched the retrieved bundle"*. The wrapper drops an id
the retriever never returned, so it never reaches the validator and can never
appear as an issue code. Counting it here is the only way to see it.

The three jobs:

1. **Invoke** — `_call_agent` runs the lambda, which is the actual agent
   call.
2. **Typed failure** — `_call_agent` also turns a provider error or bad
   model JSON into a caller-safe status. The mapping is
   `PROVIDER_ERROR_TO_STATUS` in
   [failures.py](../../python/services/api/app/workflows/failures.py): the caller
   learns which *class* of thing went wrong, never the provider's message.
3. **Trace** — `ctx.yield_output` emits a `StepRecord`: the agent, status,
   the model that actually served the call and the token count, both read
   from Agent Framework's response. That is what the **Agent workflow** panel
   renders.

The row has no duration, because the node does not time itself. The
coordinator in
[coordinator.py](../../python/services/api/app/workflows/coordinator.py) runs the
workflow with `stream=True` and reads Agent Framework's own events: the
trace rows arrive as `intermediate` events, and each node's latency is the
gap between its `executor_invoked` and `executor_completed` events.

You saw all three repair outcomes in sample 7. The **Agent workflow** panel
shows the same thing from a live run: one row per attempt, with the issue
codes that sent the recommender back.

> [!NOTE]
> Telemetry is deliberately absent from that list. Agent Framework
> instruments the graph itself — `invoke_workflow`, `executor.process`,
> `edge_group.process`, and an `invoke_agent` and `chat` span per model call — so a
> hand-written event stream would be a lower-fidelity copy. See
> [observability.py](../../python/services/api/app/observability.py); the whole
> integration is two function calls.

## 5. The contract between agents

Agents hand each other typed objects, not text. Each role's reply is parsed
into a Pydantic model from
[contracts.py](../../python/services/api/app/agents/shared/contracts.py):
`response_format` asks the model for that shape, and Agent Framework parses
the reply into it. The next executor receives the parsed object on
`PlanState`, never the model's raw text.

A reply that does not parse stops the run at that agent as
`invalid_model_json`. Its issue code is a fixed value,
`AGENT_INVALID_JSON_UNPARSEABLE`, and never the parser's message: Pydantic
quotes the offending value, and that value is model output derived from a
dealer group's evidence.

> [!NOTE]
> **"Handoff" here means passing data.** The word "handoff" in the agent
> manifests means *this* — one fixed step passing its output to the next.
> Agent Framework also has a **handoff orchestration**, where an agent
> chooses at runtime which agent to transfer control to. This repo does not
> use that. See
> [docs/orchestration-patterns.md](../../docs/orchestration-patterns.md).

**Try it.** Open `test_coordinator_invalid_json_returns_typed_failure` in
[tests/test_coordinator.py](../../python/services/api/tests/test_coordinator.py).
The fake analyst replies `not json`. Make it reply with valid JSON in the
wrong shape instead: replace `invalid_json_for="data-analyst-agent"` with
`analyst_payload={"unexpected": True}`. Run it from `python/services/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_coordinator.py -k invalid_json
```

It still passes. Valid JSON is not enough; the reply has to be the contract's
shape, and a reply that is not stops the run at the agent that produced it —
not with a `KeyError` three functions later. Revert the change afterwards.

## 6. The checks that decide pass or fail

Open [checks.py](../../python/services/api/app/agents/validator/checks.py). Every rule
is a function with the same signature, registered in one tuple:

```python
DETERMINISTIC_CHECKS: tuple[Callable[[ValidatorInput, Findings], None], ...] = (
    check_contract_version,
    check_dealer_group,
    check_catalog_membership,
    check_citations,
    check_caveats,
    check_support_tier,
    check_required_sections,
    check_forbidden_determinations,
)
```

No check short-circuits the others, so a draft that breaks three rules is
told about all three and one repair round can address everything.

`check_citations` is the one to read closely:

```python
def check_citations(payload: ValidatorInput, findings: Findings) -> None:
    if not payload.draft.citations:
        findings.flag("MISSING_CITATIONS", "citations")
        return

    allowed = set(payload.context.allowed_citation_ids)
    for citation in payload.draft.citations:
        if citation.dealer_group_id != payload.context.dealer_group_id:
            findings.flag("CROSS_DEALER_GROUP_CITATION", "citations")
        if citation.citation_id not in allowed:
            findings.flag("UNKNOWN_CITATION_ID", "citations")
```

A GROUP-B citation on a GROUP-A request is a set membership test, not a
prompt instruction. `allowed_citation_ids` came from the retriever, which was
already scoped to the requesting group.

**Try it.** Make `check_citations` return immediately. Run a request.
Nothing errors, the plan still looks right, and the guarantee is gone. Now
run `pytest` *with the check still disabled* and read which tests fail —
those tests are the guarantee, written down. Restore the check and confirm
they pass again.

To add a rule: write a function, add it to the tuple, then add the matching
entry to `_REPAIR_TEMPLATES` in
[repair.py](../../python/services/api/app/agents/validator/repair.py), which tells the
recommender how to fix it. That pairing is enforced — a test parses
`checks.py` and fails if any code you can emit has no template.

## 7. The repair bound

There is no repair *function*. The bound is the edge condition you already
read in section 3: `needs_repair` requires
`state.attempts < MAX_RECOMMENDER_ATTEMPTS`, which is 2. When it is
exhausted, `repair_exhausted` routes to `Refuse` instead, returning
`VALIDATION_FAILED_AFTER_REPAIR`. The back edge from `validate` to
`recommend` is a real cycle in the graph, but a bounded one: at most one
repair, then a typed refusal.

Two details worth copying:

- The repair pass is traced under its own name,
  `support-recommendation-agent:repair`, so you can see it happened.
- The recheck sets `use_llm_critique = plan.attempts == 1`. The critique is
  advisory and cannot change a verdict, so paying for it twice buys nothing.

The app sets no clock of its own. Agent Framework bounds a workflow by
supersteps, not seconds; each model call is bounded by the OpenAI client's
default timeout, and the request as a whole by App Service's 230-second
front-end limit.

## 8. Publish the other three roles

`publish_prompt_agents.py --roles-only` reads the three role `agent.md` files,
composes each one's instructions exactly as the running app does, and creates
a new *version* of an agent named `asg-<role>-<your-alias>`.

Dry run first — it prints what it would create and calls nothing:

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\publish_prompt_agents.py --suffix <your-alias> --roles-only
```

Add `--apply` to publish. The three role agents then appear in the portal.

![The Agents list showing three prompt agents: asg-validator-agent-demo,
asg-support-recommendation-agent-demo and
asg-data-analyst-agent-demo.](../images/module-3-three-role-agents.png)

> [!WARNING]
> **Use `--roles-only`, not a bare `--apply`.** The publisher builds each
> version from `agent.md` alone, and a bare `--apply` would also republish
> agents you later create or edit in the portal. Anything added in the portal
> — an attached knowledge base above all — is not in that file, so the new
> version comes back with `Knowledge` empty, and traffic follows the newest
> version.

The backend does not call the published agents. `_build_runtime` in
[python/services/api/app/main.py](../../python/services/api/app/main.py) loads every role from
`agent.md` when the app starts, so a prompt edit needs a backend restart but
no publish step. The published agents are the visible, versioned artifact of
the same definition. Keep them in step by re-publishing after a prompt change
and comparing the `instructions_hash` that `validate_agent_definitions.py`
prints.

## 9. Follow one request through

In the UI you opened at the start, pick a dealership and submit a concern.

The request lands on `post_recommendation` in
[python/services/api/app/routers/supports.py](../../python/services/api/app/routers/supports.py).
It is short, and it shows the division of labour between the HTTP layer and
the coordinator:

```python
request = _coordinator_request(payload, dealership, repos)
started = time.monotonic()
result = await coordinator.run(request)
```

`_coordinator_request` resolves the **allowed catalogs** before the workflow
starts:

```python
allowed_goal_ids=tuple(
    g.id for g in options.goals if g.category_id == payload.category
),
allowed_strategy_ids=tuple(
    s.id for s in options.strategies if s.category_id == payload.category
),
```

The recommender may only cite IDs this function handed it. The model does not
choose the universe it draws from.

Now read the trace. The UI panel shows a condensed view — the three agents
with provider, model, latency and status. The full trace, including the
evidence-retrieval step and per-step token counts, is in the API response
body.

> [!NOTE]
> **Coming back after Module 6? Where did my knowledge base go?**
> Skip this on a first pass — the fixture retriever is the right default here.
> Which retriever the backend uses depends on `EVIDENCE_SOURCE`, and the
> backend you started at the top of this module is the local one. Module 6's
> Terraform change set
> that variable on App Service, not on your laptop, and `populate-env.ps1`
> does not write it either — so a local run uses `FixtureEvidenceRetriever`
> unless you say otherwise. To run this module against your own knowledge
> base, add both lines to `python/services/api/.env` and restart:
>
> ```
> EVIDENCE_SOURCE=foundry_iq
> FOUNDRY_IQ_KNOWLEDGE_BASE=asg-kb-<your-alias>
> ```
>
> Check rather than assume:
>
> ```powershell
> $api = "http://127.0.0.1:8000"
> (Invoke-RestMethod "$api/api/health/details").evidence_source
> ```
>
> Either works here. Both implementations satisfy the protocol in
> [python/services/api/app/evidence/retrieval.py](../../python/services/api/app/evidence/retrieval.py),
> so the coordinator and all three agents are identical either way. Fixtures
> stay the default because they are deterministic and run offline.

## 10. Read a failure

Each typed failure is a distinct,
attributable outcome a caller can branch on:

| status | error_code | what happened |
| --- | --- | --- |
| `evidence_missing` | `EVIDENCE_MISSING` | retrieval returned nothing for this group |
| `invalid_model_json` | `AGENT_INVALID_JSON` | a model returned unparseable or off-schema JSON |
| `validation_failed` | `VALIDATION_FAILED_AFTER_REPAIR` | the validator rejected both attempts |
| `provider_timeout` | `AGENT_PROVIDER_TIMEOUT` | the model call timed out |
| `provider_throttling` | `AGENT_PROVIDER_THROTTLING` | out of tokens-per-minute quota |
| `provider_content_filter` | `AGENT_PROVIDER_CONTENT_FILTER` | a guardrail blocked the call |
| `provider_error` | `AGENT_PROVIDER_AUTH_DENIED` | the identity lacks a role |
| `provider_missing` | `AGENT_PROVIDER_MISSING` | no Foundry project is configured |

The provider rows come from `PROVIDER_ERROR_TO_STATUS` in
[python/services/api/app/workflows/failures.py](../../python/services/api/app/workflows/failures.py),
which is the single table mapping an SDK exception type to a caller-visible
status. Throttling and a content-filter block are different problems with
different fixes, so they get different codes.

**Produce one.** Stop the backend, blank `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
in `python/services/api/.env`, restart, and submit a request. You get
`provider_missing`, no recommendation body, and no stack trace. Put the
endpoint back and restart before continuing.

Nothing about this requires three agents. What produces it is the wrapper:
`classify_provider_error` turning an SDK exception into a status, and
`StepFailed` carrying that status out of the run. A single-agent service can
have the same property, and most do not — they return prose, and the caller
has nothing to branch on.

## Check yourself

- [ ] The three role agents appear in the portal with your suffix.
- [ ] You ran the flow and read a complete trace.
- [ ] You can point at the line that stops a cross-group citation.
- [ ] You produced at least one typed failure on purpose.
- [ ] You checked whether your trace shows a repair pass on every run.

Next: [Module 4 — Prompt agents](module-4-prompt-agents.md)
