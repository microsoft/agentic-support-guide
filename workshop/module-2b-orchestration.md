# Module 2B — From one agent to three

**Time:** about 60 minutes.

**You will have at the end:** a running three-agent workflow, and a working
understanding of why the coordination lives in code rather than in a prompt.

---

## The problem you are fixing

Your Module 2A agent is grounded and cites sources. It still cannot promise:

- that a recommendation draws only on **one district's** evidence
- that every claim carries a citation
- that invalid output gets **retried** rather than shipped
- that the whole thing finishes inside a time budget

These are process guarantees. You cannot ask a model to guarantee something —
you can only ask it to try, and check afterwards.

## The shape

```
Request
  |
  v
District-scoped evidence retrieval        <- before any model call
  |
  v
Data Analyst Agent      -> analysis      -> schema validation
  |
  v
Support Recommender     -> draft         -> schema validation
  |
  v
Validator Agent         -> pass/fail + repair guidance
  |
  +-- failed --> Recommender, one repair attempt --> Validator
  |
  v
Recommendation, or an explicit refusal
```

Three agents, one deterministic coordinator. The coordinator is not an agent
and does not use a model. It is ordinary code, which is exactly why it can
make guarantees.

## 1. Publish all three roles

Module 1 used `--workshop-only`. Drop it:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_prompt_agents.py --suffix <your-alias> --apply
```

All four agents now appear in the portal. They are published from the same
`agent.md` files the running app composes its instructions from, so the
portal shows the same definition the app runs.

**But be precise about what executes.** The backend does *not* call the
published agents. It composes each role in-process from `agent.md` on every
request, which is what makes a prompt edit take effect immediately with no
publish step. The published agents are the visible, versioned artifact of
the same definition. Keep them in step by re-publishing after a prompt
change, and compare the `instructions_hash`.

## 2. Run it

Two terminals — both commands block:

```powershell
# Terminal 1
.\scripts\run-backend.ps1
```

```powershell
# Terminal 2
.\scripts\run-frontend.ps1
```

Then open <http://127.0.0.1:5173>, pick a learner, and submit a concern.
Watch the agent trace: each step shows the agent, its status, the model that
actually served it, latency, and token counts.

> **Read this before you wonder where your knowledge base went.**
> The backend uses `FixtureEvidenceRetriever` — the in-repo synthetic
> evidence — **not** the Foundry IQ knowledge base you built in Module 2A.
> There is no Foundry IQ retriever implementation in this repo yet.
>
> That is deliberate for a workshop: the fixtures are deterministic, run
> offline, and keep CI independent of Azure. But it means Module 2B is
> demonstrating *orchestration*, not *your* grounding. The
> `EvidenceRetriever` protocol is async precisely so a Foundry IQ
> implementation can be dropped in without touching the coordinator or the
> agents — that swap is the natural exercise to take home.

## 3. Read the guarantees in the code

Open [services/api/app/workflows/coordinator.py](../services/api/app/workflows/coordinator.py)
and find each of these.

**Evidence retrieval happens first.** Before any model call. Grounding is not
left to the model's discretion — it is a precondition.

**Every message is schema-validated.** Against `contracts/v1/`. When a model
returns valid JSON that does not match the contract, you get
`PROTOCOL_VALIDATION_FAILED` naming the schema — not a confusing downstream
crash.

**Citations are checked against an allow-list.** A DIST-B citation on a
DIST-A request is refused. No prompt makes this reliable; a set membership
test does.

**Repair is bounded to one attempt.** Unbounded retry against a
non-deterministic system is how you build a very expensive infinite loop.

**There is a total budget.** Each step checks the deadline, and per-call
timeouts are clamped to what remains. One slow call cannot consume the whole
request.

**Failures are typed.** `evidence_missing`, `validation_failed`,
`invalid_model_json`, `orchestration_budget_exhausted` — each is a distinct,
attributable outcome, not a generic error.

## 4. Break it deliberately

Each of these should fail in a *specific* way, not a generic one.

1. **Unknown district.** Submit with a district that has no evidence.
   Expect `evidence_missing` — and note that it fails *before* spending a
   single model call.
2. **Cross-district citation.** In the validator context, allow a citation
   from another district. Expect refusal.
3. **Off-contract output.** Loosen a field in the recommender's `agent.md`.
   Expect `PROTOCOL_VALIDATION_FAILED` naming the schema.
4. **Budget exhaustion.** `ORCHESTRATION_TOTAL_BUDGET_SECONDS` is a constant
   in [services/api/app/config.py](../services/api/app/config.py), not an
   environment variable. Lower it to `1.0`, restart the backend, and re-run.
   Expect `orchestration_budget_exhausted` with a partial trace showing how
   far it got. Put it back afterwards.

Compare each to what a single prompt agent would have done: returned
something plausible.

## 5. A bug worth learning from

Three bugs in this workflow shipped past a full green test suite. All three
were only found by running it against Azure.

The most instructive: the validator required the literal phrase
`"human review"`, while the recommender's prompt said `"human-review"`. Every
single run failed validation, triggered a repair pass, and passed on the
second attempt. Nothing errored. Output was correct. It just cost an extra
model call and about twelve seconds — *every time* — and no test caught it,
because every test asserted on the final result.

The lesson is not "write more tests." It is that **green tests do not mean
working software**, and that traces showing per-step latency are how you find
the difference. Look at your own trace now. Is anything running twice?

## 6. Where the boundary sits

| Belongs in the prompt | Belongs in code |
| --- | --- |
| Tone, role, format | Schema validation |
| Domain reasoning | Retry and repair policy |
| What to prioritise | District scoping |
| When to say "I don't know" | Timeouts and budgets |
| | Allow-list membership |

A useful rule: if you would be uncomfortable telling a customer "the model
usually gets this right," it belongs in code.

---

## Check yourself

- [ ] All four agents appear in the portal with your suffix.
- [ ] You ran the flow and read a complete trace.
- [ ] You triggered at least three distinct typed failures.
- [ ] You checked whether your trace shows a repair pass on every run.

## What you should be able to explain

- Why the coordinator is not itself an agent.
- Why repair is capped at one attempt.
- Why evidence retrieval happens before any model call.

Next: [Module 3 — Model router](module-3-model-router.md)
