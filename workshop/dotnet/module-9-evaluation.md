# Module 9 — Evaluate the agents

**Time:** 25 minutes.

**You will have at the end:** numeric grades for your agent's answers, a
threshold that fails the build when quality regresses, and a clear sense of
what these graders can and cannot tell you.

---

## Two different questions

The validator's deterministic checks, which you read in Module 3, answer:

> Is the output structurally valid, correctly shaped, dealer group-scoped, and
> free of prohibited language?

They pass or fail the same way every time, they need no model, and they run
on every request.

They cannot answer:

> Is this answer actually grounded in the evidence? Does it actually address
> what was asked?

That needs a judge. This module adds one.

Keep both. Deterministic checks are your fast, free, reliable gate;
model-graded evaluation is slower, costs tokens, and is itself
non-deterministic. Anything you *can* express as a deterministic check,
should be.

## What a grader actually is

A grader — also called an evaluator, and the model behind it a judge — is a
prompt plus a rubric. The service sends a second model the question, the
answer, and (for some graders) the source material, and asks it to score the
answer against written criteria on a 1–5 scale and explain why.

That is worth saying plainly because it sets the limits:

- The score is a model output. It varies between runs.
- The judge only sees what you send it. A grader that needs source material
  and does not get it will score confidently and wrongly, which is exactly
  what happened to this workshop — see §6.
- A rubric is a text document. Two graders with similar names can measure
  quite different things.

## 1. Run the deterministic checks first

The test suite proves each check fires. Run the tests that guard the output
— no Azure, no tokens:

```powershell
dotnet test --solution dotnet\AgenticSupportGuide.slnx `
    --filter-class "*.AgentsTests" --filter-class "*.ValidatorCitationChecksTests" `
    --filter-class "*.ValidatorHardeningTests" --filter-class "*.DeterminationsTests"
```

They should all pass.

Open [Checks.cs](../../dotnet/services/api/AgenticSupportGuide.Api/Agents/Validator/Checks.cs).
Notice what the checks deliberately do *not* do: they never assert on exact
model prose. They check structure, catalog membership, dealer group scoping,
and the presence of the human-review caveat:

```csharp
public static void CheckCaveats(ValidatorInput payload, Findings findings)
{
    if (payload.Draft.Caveats.Count == 0)
    {
        findings.Flag("MISSING_CAVEATS", "caveats");
        return;
    }
    var caveatText = PyText.Lower(string.Join(" ", payload.Draft.Caveats));
    if (!RequiredKeywordCaveats.All(keyword => caveatText.Contains(keyword, StringComparison.Ordinal)))
    {
        findings.Flag("MISSING_HUMAN_REVIEW_CAVEAT", "caveats");
    }
}

public static void CheckSupportTier(ValidatorInput payload, Findings findings)
{
    var tier = PyText.Lower(payload.Draft.SupportTier);
    if (!RequiredTierPatterns.Any(pattern => tier.Contains(pattern, StringComparison.Ordinal)))
    {
        findings.Flag("INVALID_SUPPORT_TIER", "support_tier");
    }
}
```

Prose varies between runs and between model versions. Locking it down creates
a test that fails for the wrong reasons.

Note that none of these checks short-circuit either. A draft that breaks
three rules is told about all three, so one repair round can address
everything.

## 2. Grade your agent in the portal

Do this by hand before you automate it. The portal is where you will
investigate a bad score later, so learn the surface first.

**Build → Evaluations → Create.** It is a six-step wizard.

1. **Target** — what is being graded. Choose **Agent**, then tick
   `asg-support-explainer-agent-<your-alias>`. Note the **Version** column:
   you are grading one specific version, not "the agent". A score belongs to
   a version or it means nothing.
2. **Scope** — how much of an interaction each grade covers. **Individual
   turns** grades one question and one answer, which is what your agent does.
   *Full conversations* grades a multi-turn exchange end to end.
3. **Frequency** — **One time** runs once now. *Recurring* runs the same
   evaluation on a schedule, which is continuous monitoring rather than a
   one-off check. You can switch an existing evaluation to recurring later
   from its detail page.
4. **Data** — where the questions come from. **Synthetic generation** has the
   portal write questions for you. **Existing dataset** uses questions you
   upload. **Benchmarks** uses public question sets. **Existing traces** grades
   real production interactions. Pick **Synthetic generation** and choose your
   chat deployment.
5. **Criteria** — which graders to run. Choose `groundedness`, `relevance` and
   `coherence`; §4 explains why those three and not the others.
6. **Review** — submit.

> [!TIP]
> The job queues and runs on Foundry's schedule, not yours — several minutes
> is normal. Submit it now and carry straight on to §4 and §5 while it works.
> Come back to §3 once it reports Completed. Waiting at this screen is the
> single easiest way to lose ten minutes of this module.

Two things worth knowing before you pick **Existing traces**, because it is
the option you will want in production and it will not work here:

- It needs Application Insights connected to the **project** for tracing.
  Module 0's Terraform creates App Insights and wires diagnostic settings on
  the *AI Services account*, which is not the same connection. The portal
  will tell you so — "Create or connect an App Insights resource to enable
  tracing" — and the trace list stays empty.
- Even once connected, the portal warns that telemetry ingestion takes 3–5
  minutes, and advises padding your end time by ten minutes. Evaluating
  traces you generated sixty seconds ago finds nothing.

## 3. Read the scorecard

Come back here once the run you submitted in §2 reports **Completed**.

When the run completes, open it. You get a per-case view with each grader's
score *and the judge's reasoning* — which is the part a console line cannot
give you, and the reason this module has you click before it has you script.

Your runs are listed under **Build → Evaluations**. This is the page before
you have created any — note the **Evaluations**, **Evaluator catalog** and
**Red team** tabs, and that Evaluations sits under **Optimize** in the left
rail, not under Build:

![The Foundry Evaluations page under Optimize, with the Evaluations,
Evaluator catalog and Red team tabs, and an empty run list reading "No
evaluations found".](../images/module-9-evaluations.png)

## 4. See what graders are available

In the portal, **Build → Evaluations → Evaluator catalog** is the library the
Criteria step draws from. Open it and read what each grader claims to
measure — the wording of the claim is the rubric.

The same list from a shell, which is what you want when wiring a gate:

```powershell
dotnet run dotnet/scripts/run_agent_evals.cs -- --list-evaluators
```

Nineteen built-in graders. The ones that matter for a grounded advisory agent:

| Grader | Question it answers | Needs |
| --- | --- | --- |
| `groundedness` | Is every claim supported by the source text supplied? | `context` |
| `relevance` | Does the answer address the question asked? | — |
| `coherence` | Does the answer hold together — consistent, ordered, not self-contradicting? | — |
| `similarity` | How close is this to a known-good answer? | ground truth |
| `task_adherence` | Did it stay inside the job its instructions describe? | — |

`groundedness` is the only one of these that can catch a confident invention,
and it only works if you hand it the source text. `similarity` has a harder
requirement still — a reference answer per case, which
[evals/synthetic_cases.jsonl](../../evals/synthetic_cases.jsonl) does not carry,
so it is not wired into the script.

The `tool_*` and `task_navigation_*` graders apply to multi-step,
tool-calling agents. They will not tell you anything useful about a
single-turn agent.

The safety graders (`violence`, `self_harm`, `hate_unfairness`, `sexual`)
overlap with the Module 8 guardrails. Guardrails *block* at runtime; these
*measure* after the fact. Use both, for different purposes.

## 5. Now make it repeatable

The portal run graded questions it invented. That is fine for learning the
surface and wrong for catching regressions: you cannot compare two runs whose
questions differ, and generated questions will not happen to cover the case
you already know is hard.

[evals/synthetic_cases.jsonl](../../evals/synthetic_cases.jsonl) is six
*curated* cases, fixed and version-controlled, chosen to include a
known-difficult one. That is what a gate needs.

```powershell
dotnet run dotnet/scripts/run_agent_evals.cs -- --dry-run
```

This prints the six cases and how much grounding context each one carries,
without calling Azure. The context is built from the same dealer group
fixtures the agents use, which matters: `groundedness` is scored *against
that text*.

Then grade against the model:

```powershell
dotnet run dotnet/scripts/run_agent_evals.cs -- --apply
```

**This does not grade the agent you ticked in §2.** It builds an ephemeral
agent called `asg-eval-support-explainer` from `agents/support-explainer/`
and grades that. The difference is deliberate — a gate must grade what is in
source control, not what somebody last saved in a browser — but it means the
two sets of scores are not comparable, and a knowledge base or guardrail you
attached in the portal is not present here.

### Read how the harness runs a case

`GradeAllAsync` in [dotnet/scripts/run_agent_evals.cs](../../dotnet/scripts/run_agent_evals.cs):

```csharp
// Evaluating with the agent itself would send it the bare query and
// attach `context` to the grading item only, so the agent would
// answer blind and groundedness would score it against evidence it
// never saw. Run it ourselves with the evidence, then grade that
// response against the clean question.
var response = await agent.RunAsync(new ChatMessage(ChatRole.User, GroundedPrompt(query, context)));
var item = new EvalItem(query, response.Text, [new ChatMessage(ChatRole.User, query), .. response.Messages])
{
    Context = context,
};
var caseId = testCase.GetProperty("id").ToString();
var results = await grader.EvaluateAsync([item], $"asg-{caseId}");
```

`grader` is Agent Framework's `FoundryEvals`, built with the judge deployment
and the graders you chose. `GroundedPrompt` reuses the app's fence delimiters
so the agent is told to treat the block as data. It shares the delimiters, not
the protection — it does not call `WrapUntrusted`, so fixture text is not
fenced or length-bounded on the way in. Acceptable for a harness reading
in-repo fixtures; not for anything reading real documents.

Expect a few minutes — every case is at least two model calls, one to answer
and one to grade.

```
  [fail] eval-001  coherence=4.00, groundedness=4.00, relevance=2.00
           grader rejected: relevance
  [ok  ] eval-002  coherence=4.00, groundedness=5.00, relevance=4.00
  [ok  ] eval-003  coherence=4.00, groundedness=3.00, relevance=4.00
  [ok  ] eval-004  coherence=5.00, groundedness=5.00, relevance=5.00
  [ok  ] eval-005  coherence=4.00, groundedness=5.00, relevance=4.00
  [ok  ] eval-006  coherence=4.00, groundedness=5.00, relevance=3.00

5/6 case(s) passed the quality gate.
```

**Do not expect to reproduce those numbers, including the failure.** That run
is one sample. The agent is generating fresh prose each time and a second
model is grading it, so both halves vary; the same case can pass one run and
fail the next without a line of code changing. The scores above sat between
2.00 and 5.00 across six cases.

This matters more than it first looks. A gate that flips on identical input
cannot tell you whether a change was an improvement. Before you act on a
single failing case, run it again — and if you intend to use this in CI, look
at `numRepetitions` on Agent Framework's `EvaluateAsync` agent extension and
judge a case on several runs rather than one.

### Read how a result becomes pass or fail

Two rules in `Report` are the difference between a gate and a rubber stamp:

```csharp
var scores = CollectScores(runs);
if (scores.Count == 0)
{
    Console.WriteLine($"  [fail] {caseId}: grader returned no scores - nothing was graded");
    return true;
}

var below = scores.Where(s => s.Score < PassThreshold).Select(s => s.Name).ToList();
var rejected = scores.Where(s => s.Passed == false).Select(s => s.Name).ToList();
// A grader that errored leaves no score, and the others can still pass.
var ungraded = expected.Except(scores.Select(s => s.Name), StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();
// A missing verdict is a failed verdict: defaulting to true would let an
// SDK shape change silently turn a regression into a green run.
var allPassed = runs.All(r => r.AllPassed);
var regressed = below.Count > 0 || rejected.Count > 0 || ungraded.Count > 0 || !allPassed;
```

A run that produced no scores is a failure, not a pass — nothing was graded.
So is a case where one grader errored and the others scored: any grader in
`expected`, the ones you asked for, that has no score is listed as
`not graded` and the case fails, rather than passing on the scores that
happened to come back.
A missing verdict is treated as a failed verdict, so an SDK response-shape
change breaks the build rather than turning every run green.

Grades are 1-5 and `PassThreshold` is 3.0. The exit code is what makes this
usable as a gate. Runs land in the same **Build → Evaluations** list.

## 6. When a score is wrong about what is broken

Grader scores also go wrong in a way repetition will not fix. An earlier
version of this workshop recorded this:

```
  [fail] eval-005  coherence=4.00, groundedness=2.00, relevance=3.00
```

`eval-005` is the multi-area case — enquiries, test drives and listings at
once — so the reading looked obvious: the agent is padding across areas where
the evidence is thin. That reading was written into this module, and it was
wrong.

The agent was never given the evidence. Evaluating through the agent itself
sends the bare question to the agent and attaches `context` to the *grading*
item only, so the agent answered from prior knowledge while `groundedness`
scored it against text it had never seen. The multi-area case scored lowest
because it was the one where guessing showed most. Fixing the harness — the
code in §5 — lifted groundedness across the board without touching a single
prompt.

A low groundedness score tells you the answer is not supported by the
context. It does not tell you why, and the cause is not always the agent.
Check that your harness gave the model what you are grading it
against — `--dry-run` prints the context length for exactly this reason.

So when something does fail:

- Is the evidence actually there for that dealer group and category? Run
  `--dry-run` and look at the context length. Zero chars is a harness bug.
- Did the agent *see* that evidence, or only the grader?
- Is the agent citing evidence it was given, or asserting beyond it?
- Is the judge wrong? Judges are models. They are not oracles.

Then try a fix — usually a tightened `constraint` in `agent.md` — and re-run.
That moves the scripted score immediately. The portal score will not move
until you re-publish, because the portal is grading a stored version.

## 7. Optional — wire it into a build

**Skip this whole section if you are not doing CI.** Nothing later in the
workshop depends on it. The learning outcome of this module is reading and
interpreting scores, which you have already done.

Two useful gates:

```powershell
# Fast, free, deterministic. Run on every commit.
dotnet test --solution dotnet\AgenticSupportGuide.slnx

# Slow, costs tokens, non-deterministic. Run before a release.
dotnet run dotnet/scripts/run_agent_evals.cs -- --apply
```

Do not put the graded evaluation on every commit. It is slow, it costs money,
and because it is non-deterministic it will eventually fail on an unchanged
prompt and teach your team to ignore red builds.

### Run both gates in GitHub Actions

This needs the app registration from
[Module 1](module-1-deploy-the-app.md), and nothing later depends on it.

The deterministic gate is already wired.
[.github/workflows/ci-dotnet.yml](../../.github/workflows/ci-dotnet.yml) runs
the test suite on every pull request, alongside the build. It needs no Azure
credentials, because the tests call nothing.

The graded one is [.github/workflows/evaluate-dotnet.yml](../../.github/workflows/evaluate-dotnet.yml),
and it is `workflow_dispatch` only — the same reasoning as above, expressed
in the trigger rather than in a team norm nobody remembers.

It reads three variables from the `workshop-dotnet` environment:

```powershell
gh variable set AZURE_AI_FOUNDRY_PROJECT_ENDPOINT --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw foundry_project_endpoint)
gh variable set FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw model_deployment_name)
gh variable set FOUNDRY_MODEL_DEPLOYMENT_JUDGE --env workshop-dotnet --body (terraform -chdir=dotnet/infra output -raw judge_deployment_name)
```

> [!IMPORTANT]
> **Contributor on the resource group is not enough.** That is a control-plane
> role, and it lets the workflow create and delete the Search service without
> ever being allowed to send a prompt through your project. Grading is
> data-plane work in two places, so grant the same service principal both
> roles [dotnet/infra/rbac.tf](../../dotnet/infra/rbac.tf) gives you, before
> you run anything: `Cognitive Services User` on the **project**, where the
> agent runs, and `Cognitive Services OpenAI User` on the **AI Services
> account**, where the graders call the judge deployment:
>
> ```powershell
> $spObjectId = az ad sp show --id <appId> --query id -o tsv
> az role assignment create --assignee-object-id $spObjectId `
>     --assignee-principal-type ServicePrincipal --role "Cognitive Services User" `
>     --scope (terraform -chdir=dotnet/infra output -raw foundry_project_id)
> az role assignment create --assignee-object-id $spObjectId `
>     --assignee-principal-type ServicePrincipal --role "Cognitive Services OpenAI User" `
>     --scope (terraform -chdir=dotnet/infra output -raw ai_services_account_id)
> ```
>
> `<appId>` is the app registration from Module 1. Its *object* ID is not the
> same value, which is why the first line looks it up.
>
> Without either grant the deploy workflow keeps working and only this one
> fails, and neither failure mentions roles. Without the first, the agent call
> gets a 401 from the project endpoint. Without the second, the evaluation
> runs complete in the portal, every grader errors with `PermissionDenied` on
> `chat/completions`, and the script prints `grader returned no scores` for
> every case. A new grant also takes a while to reach every model endpoint —
> well over ten minutes here — and until it does, some graders score and the
> rest come back `not graded`.

Then:

```powershell
gh workflow run evaluate-dotnet.yml
gh run watch --exit-status
```

Results go to the job log, not an artifact — `run_agent_evals.cs` prints its
scores and exits non-zero on a failure, which is what a gate needs.

---

## Limitations

Read this before you quote scores to anyone.

- **`FoundryEvals` ships in a preview package.** `Microsoft.Agents.AI.Foundry`
  is a prerelease, so the API can change between releases. Pin your versions
  and expect churn.
- **The judge is a model.** It has its own biases and failure modes. A 5.0 is
  not proof of correctness; it is one model's opinion.
- **Six synthetic cases is not a benchmark.** It catches gross regressions.
  It does not characterise quality. Real evaluation needs real, curated,
  many-case datasets — ideally from production traces.
- **`groundedness` measures support, not truth.** An answer perfectly grounded
  in wrong evidence scores 5.0.
- **Nothing here is a determination.** These are synthetic dealerships and
  synthetic dealer groups. No output of this system, graded or not, is a
  pricing, financing, credit, compliance, or safety determination. A human
  reviews everything.

## Check yourself

- [ ] You created an evaluation in the portal and read a judge's reasoning.
- [ ] You ran the deterministic checks and the graded evaluation.
- [ ] You can explain why both exist.
- [ ] You can explain what a low groundedness score does and does not tell you.
- [ ] You can name two things a groundedness score of 5.0 does *not* prove.

Next: [Module 10 — Operate what you built](module-10-operate.md)
