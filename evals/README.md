# Evaluations

Synthetic evaluation cases and structural/safety checks for the three
agents. All cases use synthetic learners only. Evaluation runs never
capture full prompts or full completions in committed files.

## Layout

- `synthetic_cases.jsonl` — one synthetic support-planning case per line.
- `expected_checks.yaml` — structural and safety checks that must hold
  for the coordinator output on each case.
- `results/` — gitignored. Local eval outputs go here.

## Running evaluations

The runtime path uses **real Azure AI Foundry** LLM calls. Evals hit the
same coordinator that the demo hits; they do not bypass safety or
validation.

### Prerequisites

1. Backend is running against Azure AI Foundry
   (`.\scripts\verify-demo.ps1` should print `Ready for customer demo`).
2. `services/api/.env` is populated.
3. The synthetic mock repositories are seeded — the backend does this
   automatically on startup.

### Basic eval loop (manual)

The prototype does not ship a bundled eval runner. A minimal manual
loop looks like this:

```powershell
# 1. Start the backend in one terminal.
.\scripts\run-backend.ps1

# 2. In another terminal, hit each case.
foreach ($line in Get-Content .\evals\synthetic_cases.jsonl) {
    $case = $line | ConvertFrom-Json
    $body = @{
        learner_id   = $case.learner_id
        category     = $case.category
        concern_text = $case.concern_text
    } | ConvertTo-Json
    $rec = Invoke-RestMethod `
        -Uri http://127.0.0.1:8000/api/recommendations/support-plan `
        -Method Post -Body $body -ContentType "application/json"
    "$($case.id): status=$($rec.status)" | Out-File -Append `
        .\evals\results\summary.txt
}
```

### What to check

The runtime deterministic validator already enforces the majority of
what `expected_checks.yaml` documents:

- Structured JSON conforming to the contract.
- Support tier framing.
- Human-review caveat presence.
- Allowed resource / SMART goal / strategy IDs only.
- Progress-monitoring and educator-next-step presence.

`expected_checks.yaml` is the human-review reference for what a good
run looks like. It is not machine-executed today; wire it into a small
evaluator only if the demo road-map requires it.

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
