# Evaluations

Synthetic evaluation cases and structural/safety checks for the three
agents. All cases use synthetic dealerships only. Evaluation runs never
capture full prompts or full completions in committed files.

## Layout

- `synthetic_cases.jsonl` — one synthetic support-planning case per line.
- `expected_checks.yaml` — structural and safety checks that must hold
  for the coordinator output on each case.
- `results/` — gitignored. Local eval outputs go here.

## Running evaluations

[`scripts/run_evals.py`](../scripts/run_evals.py) scores every case in
`synthetic_cases.jsonl` against `expected_checks.yaml`. It has two modes.

### Offline (the CI gate)

```powershell
cd services\api
python ..\..\scripts\run_evals.py --offline
```

Runs the real coordinator against in-repo fixtures. No Azure, no cost, no
credentials. This is what runs on every pull request, so a change that
breaks grounding, tier framing, the human-review caveat, or the failure
paths fails the build.

### Live (against a running backend)

```powershell
python scripts\run_evals.py --live http://127.0.0.1:8000
```

Calls a backend configured for Azure AI Foundry, so it exercises real
model output. Use this before a demo or after changing an `agent.md`.
It costs tokens, so it is deliberately not in CI.

## What is graded

Structure and safety, never prose. Model wording varies between runs and
model versions; the checks that matter are:

- the envelope is well formed and the trace contains all three agents
- `status=ok` carries a recommendation with `completeness.ok == true`
- support tier uses baseline / focused / intensive / advanced framing
- `review_window_days` is between 7 and 180
- caveats contain the literal phrase `human review`
- at least one citation is present, and every citation belongs to the
  same dealer group as the recommendation
- every free-text field contains no determination language
  (pricing, financing, credit, compliance, safety, staffing)
- on a non-ok status, no recommendation body leaks and an `error_code`
  is present

Adding a case is one line in `synthetic_cases.jsonl`. It must include
`dealer_group_id`, and its dealer group/category pair must have evidence
fixtures, or the run is ungrounded by construction.
`services/api/tests/test_eval_cases.py` enforces both.

## What must never be captured

- Full prompts.
- Full completions.
- Raw concern text beyond what is in `synthetic_cases.jsonl` itself
  (which is synthetic).
- Any endpoint, connection string, or Azure resource ID.

Committed eval artifacts must be **structural summaries only**:
per-case pass/fail flags, counts of issue/warning codes, and latency
buckets. The full model output stays in `/evals/results/` and never
gets committed (the `.gitignore` at the repo root excludes it).
