# Module 6 — Evaluate the agents

**Time:** about 60 minutes.

**You will have at the end:** numeric grades for your agent's answers, a
threshold that fails the build when quality regresses, and a clear sense of
what these graders can and cannot tell you.

---

## Two different questions

You have been running `scripts/run_evals.py` since Module 0 without
necessarily noticing what it does. It answers:

> Is the output structurally valid, correctly shaped, district-scoped, and
> free of prohibited language?

Those are deterministic checks. They pass or fail the same way every time,
they need no model, and they run offline in about a second.

They cannot answer:

> Is this answer actually grounded in the evidence? Does it actually address
> what was asked?

That needs a judge. This module adds one.

Keep both. Deterministic checks are your fast, free, reliable gate;
model-graded evaluation is slower, costs tokens, and is itself non-
deterministic. Anything you *can* express as a deterministic check, should be.

## 1. Run the deterministic checks first

```powershell
cd services\api
.\.venv\Scripts\python.exe ..\..\scripts\run_evals.py --offline
```

All six cases should pass. Note that this made no Azure calls at all.

Open [evals/expected_checks.yaml](../evals/expected_checks.yaml). Notice what
it deliberately does *not* do: it never asserts on exact model prose. It
checks structure, catalog membership, district scoping, and the presence of
the human-review caveat. Prose varies between runs and between model
versions; locking it down creates a test that fails for the wrong reasons.

## 2. See what graders are available

```powershell
.\.venv\Scripts\python.exe ..\..\scripts\run_agent_evals.py --list-evaluators
```

Nineteen built-in graders. The ones that matter for a grounded advisory agent:

| Grader | Question it answers | Needs |
| --- | --- | --- |
| `groundedness` | Is this supported by the evidence provided? | `context` |
| `relevance` | Does this address the question asked? | — |
| `coherence` | Does this hold together as an answer? | — |
| `similarity` | Does this match a known-good answer? | ground truth |
| `task_adherence` | Did it stay inside its instructions? | — |

The `tool_*` and `task_navigation_*` graders apply to multi-step, tool-calling
agents. They will not tell you anything useful about a single-turn agent.

The safety graders (`violence`, `self_harm`, `hate_unfairness`, `sexual`)
overlap with the Module 4 guardrails. Guardrails *block* at runtime; these
*measure* after the fact. Use both, for different purposes.

## 3. Dry run

```powershell
.\.venv\Scripts\python.exe ..\..\scripts\run_agent_evals.py --dry-run
```

This shows the six cases and how much grounding context each one carries,
without calling Azure. The context is built from the same district fixtures
the agents use, which matters: `groundedness` is scored *against that text*.
If you grade against context the agent never saw, you are measuring the wrong
thing and the scores will be meaningless.

## 4. Grade for real

```powershell
.\.venv\Scripts\python.exe ..\..\scripts\run_agent_evals.py --apply
```

This runs your agent against each case, then submits each interaction to the
judge model. Expect it to take a few minutes — every case is at least two
model calls, one to answer and one to grade.

Output is one line per case:

```
  [ok  ] eval-001  coherence=4.00, groundedness=5.00, relevance=4.00
  [fail] eval-005  coherence=4.00, groundedness=2.00, relevance=3.00
```

Grades are on a 1–5 scale. The script fails the run when anything drops below
`PASS_THRESHOLD` (3.0).

## 5. Read the failures

`eval-005` is the multi-domain case — concerns spanning literacy, math, and
attendance at once. If it scores low on groundedness while single-domain
cases score high, that is a real, specific finding: the agent is padding
across domains where the evidence is thin.

Investigate before you react:

- Is the evidence actually there for that district and category? Run
  `--dry-run` and look at the context length.
- Is the agent citing evidence it was given, or asserting beyond it?
- Is the judge wrong? Judges are models. They are not oracles.

Then try a fix — usually a tightened `constraint` in `agent.md` — and re-run.

## 6. Wire it into your loop

Two useful gates:

```powershell
# Fast, free, deterministic. Run on every commit.
.\.venv\Scripts\python.exe ..\..\scripts\run_evals.py --offline

# Slow, costs tokens, non-deterministic. Run before a release.
.\.venv\Scripts\python.exe ..\..\scripts\run_agent_evals.py --apply
```

Do not put the graded evaluation on every commit. It is slow, it costs money,
and because it is non-deterministic it will eventually fail on an unchanged
prompt and teach your team to ignore red builds.

---

## Honest limitations

Read this before you quote scores to anyone.

- **`FoundryEvals` is experimental.** The API is marked as subject to change
  or removal. Pin your versions and expect churn.
- **The judge is a model.** It has its own biases and failure modes. A 5.0 is
  not proof of correctness; it is one model's opinion.
- **Six synthetic cases is not a benchmark.** It catches gross regressions.
  It does not characterise quality. Real evaluation needs real, curated,
  many-case datasets — ideally from production traces.
- **`groundedness` measures support, not truth.** An answer perfectly grounded
  in wrong evidence scores 5.0.
- **Nothing here is a determination.** These are synthetic learners and
  synthetic districts. No output of this system, graded or not, is an
  educational, clinical, legal, or placement determination. A human reviews
  everything.

## Check yourself

- [ ] You ran the deterministic checks and the graded evaluation.
- [ ] You can explain why both exist.
- [ ] You made a change to `agent.md` and saw a grade move.
- [ ] You can name two things a groundedness score of 5.0 does *not* prove.

## What you should be able to explain

- Why prose assertions do not belong in an eval suite.
- Why grading context must be the context the agent actually saw.
- Why the graded suite does not belong on every commit.
