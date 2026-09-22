# Customer demo

A 5–7 minute walkthrough of the running application for a customer audience.

This folder covers only the demo: how to confirm the environment is ready,
what to show, and how to reset between runs. Setting the environment up is
covered once, in the [root README](../README.md#set-up-microsoft-foundry),
and is not repeated here.

**Duration:** 5–7 minutes.
**Prerequisite:** the app running against Microsoft Foundry, per the root
README.

## Confirm the demo is ready

Run all four checks before you present.

1. `GET /api/health/details` returns `"active_provider":
   "azure_foundry_responses"`, `"foundry_project_configured": true`,
   `"agent_definitions_valid": true`, and `"customer_demo_ready": true`.
2. The in-app **Demo Guide** page shows a green *Customer demo ready*
   banner.
3. Generating a recommendation in **Supports** returns `status: "ok"` with
   a three-agent trace whose model column names a real deployment.

> [!NOTE]
> The AI Audit provider column is not one of these checks. It shows the same
> configured label on every run, including failures, so it cannot tell you
> the stack is live.

The quickest single probe:

```powershell
curl.exe -s http://127.0.0.1:8000/api/health/details | python -m json.tool
```

Look for `"customer_demo_ready": true`.

> [!NOTE]
> Role assignments take a few minutes to propagate. If the first
> recommendation returns 401 or 403, wait and retry before changing
> anything.

## The talk track

1. **Dashboard.** Show the four KPI cards and both charts. Say the values
   are synthetic, and explain that this is the operating picture.
2. **Assessments.** Change one filter (for example region `REG-001`) and show
   the *Process score distribution* bands and the *Domain averages* chart
   refresh. Point at the amber *Local rule-based output* label and note that
   not every panel needs a model.
3. **Supports.** Pick a dealership, pick *Enquiry Response*, type a short
   concern such as *"First reply to online enquiries is slower than the
   group standard."*, and select **Generate recommendation**.
4. **The three agents.** While it runs, name each one in plain language:
   the Data Analyst reviews evidence, the Support Recommendation agent
   proposes options, the Validator checks safety, structure and grounding.
5. **The recommendation.** Show detected need, support tier, frequency,
   grouping, review window and the human-review caveat. Point out that the
   output is structured JSON validated against a contract, not free text.
6. **What ran on this output.** The enforcement receipt sits above the plan
   card, headed *What ran on this output*. It states what the application
   enforced: the retrieval scope, how many citation ids the model proposed
   versus how many matched, how many deterministic checks were applied, and
   what the run cost in tokens and time.
7. **AI Audit.** Show the new runtime row. Only metadata is stored — no
   prompts, completions, concern text or secrets.
8. **Close.** All data is synthetic. This is a prototype for architecture
   and workflow patterns.

Keep the language generic. Do not name a real customer, product, person,
meeting or document.

## Reset between practice runs

Application state is in memory, so stopping and restarting `uvicorn` is the
simplest reset.

For repeated practice, set `DEMO_RESET_ENABLED=true` in `services/api/.env`,
**restart the backend** so it picks the setting up, then call:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/api/demo/reset
```

> [!WARNING]
> `DEMO_RESET_ENABLED=true` is for development machines only. Never set it
> in production.

## If something fails mid-demo

- **Recommendation returns a setup error.** Foundry is not configured. The
  Setup Status panel names the missing piece.
- **401 or 403 on the first call.** Role assignment propagation. Retry.
- **The evidence source says `fixture`.** The app is serving canned evidence
  rather than retrieved evidence. Check `evidence_source` on
  `/api/health/details`, or the `evidence-retrieval` row in the agent trace
  — not the AI Audit provider column, which always shows the same label.
  Serving fixtures is a valid configuration, but say so rather than claiming
  grounding.
