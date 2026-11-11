# Evaluations

Synthetic evaluation cases for the agents. All cases use synthetic
dealerships only. Evaluation runs never capture full prompts or full
completions in committed files.

## Layout

- `synthetic_cases.jsonl` — one synthetic support-planning case per line.
- `results/` — gitignored. Local eval outputs go here.

## Running evaluations

The cases are graded with Microsoft Agent Framework's evaluation and
Foundry's built-in graders. Module 9 walks through it:

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\run_agent_evals.py --dry-run
.\python\services\api\.venv\Scripts\python.exe python\scripts\run_agent_evals.py --apply
```

`--dry-run` prints the plan and calls nothing. `--apply` calls a model for
every case and a grader for every score, so it costs tokens and is not in
CI. The **Evaluate** workflow runs it on demand.

## What is graded

Quality, on a 1 to 5 scale, by a judge model that is a different deployment
from the agents' own:

- **groundedness** — is the answer supported by the case's evidence?
- **relevance** — does it address the question?
- **coherence** — does it read as one consistent answer?

A score below 3 fails the case.

Structure and safety are not graded here, because they are not left to
chance. The validator's deterministic checks refuse a draft with a citation
from another dealer group, an out-of-catalog resource, a missing human-review
caveat or determination language, and the test suite proves each check
fires.

Adding a case is one line in `synthetic_cases.jsonl`. It must include
`dealer_group_id`, and its dealer group/category pair must have evidence
fixtures, or the run is ungrounded by construction.
`python/services/api/tests/test_eval_cases.py` enforces both.

## What must never be captured

- Full prompts.
- Full completions.
- Raw concern text beyond what is in `synthetic_cases.jsonl` itself
  (which is synthetic).
- Any endpoint, connection string, or Azure resource ID.

Committed eval artifacts must be **summaries only**: per-case scores and
pass/fail flags. The runner prints those and does not persist model output;
anything you capture yourself belongs in the gitignored `results/` directory
and never gets committed (the `.gitignore` at the repo root excludes it).
