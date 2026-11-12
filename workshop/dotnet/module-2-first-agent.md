# Module 2 — Your first agent

**Time:** 25 minutes.

**You will have at the end:** an agent you wrote yourself, a tool it can
call, and a conversation it can remember — running on your laptop against the
models Module 0 deployed.

---

Modules 0 and 1 stood up infrastructure and deployed a service that already
runs a three-agent workflow. You have seen it work without seeing how. This
module and the next build that machinery back up from the smallest thing that
works, so nothing in it stays a black box.

Four short programs in [code/](code/). Each one runs, prints something, and
adds one idea to the one before it. Module 3 continues with three more.

You should be comfortable with C# — `async`/`await`, records, lambdas and
attributes all appear. You do not need to have written an agent before.

These are **adapted from** the
[Agent Framework get-started path](https://learn.microsoft.com/agent-framework/get-started/?pivots=programming-language-csharp),
using one running example — a support explainer for a car dealership group —
so each file is a small diff from the one before it. Two steps of that path
are deliberately not here: memory/persistence and the Agent Harness. Neither
is needed to understand this repo, and both are linked at the bottom.

Each sample is a single `.cs` file that .NET 10 runs directly — no project
file to create. The `#:package` and `#:include` lines at the top of a file
are how a file-based program names its NuGet packages and pulls in the shared
setup in [_shared.cs](code/_shared.cs). Package versions come from the repo's
central [Directory.Packages.props](../../dotnet/Directory.Packages.props), so
the samples run on the same Agent Framework build as the app.

## Setup

If you did Module 0, everything is already in place: the samples read
`dotnet/services/api/.env` and use the `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and
`FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER` that `populate-env.ps1` wrote.

If you skipped ahead, you need any Foundry project you can reach and any chat
model deployed in it. Set the two names the Agent Framework docs use:

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = "https://<your-project>.services.ai.azure.com/api/projects/<name>"
$env:FOUNDRY_MODEL = "<your model deployment name>"   # the deployment, not the model
az login
```

`FOUNDRY_MODEL` is a *deployment* name from your project — `asg-chat` if you
did Module 0, whatever you called yours otherwise. A sample that cannot find
either setting prints which variable to set and exits.

Run any sample from the repo root with:

```powershell
dotnet run workshop/dotnet/code/01_first_agent.cs
```

The first run of each file restores its packages and compiles it, which takes
a few seconds; later runs reuse the build until you edit the file.

## The ladder

| # | File | The one new idea |
| --- | --- | --- |
| 1 | [01_first_agent.cs](code/01_first_agent.cs) | An agent is a model + instructions. |
| 2 | [02_add_tools.cs](code/02_add_tools.cs) | A tool is a C# method the model may call. |
| 3 | [03_multi_turn.cs](code/03_multi_turn.cs) | A session carries conversation history. |
| 4 | [04_grounding_rag.cs](code/04_grounding_rag.cs) | RAG: retrieve, augment, generate. |

Run all four. Module 6 builds directly on sample 4.

Defining an agent declaratively rather than in code is Module 4's subject.
It uses this repo's own format — `agents/<id>/agent.md` plus `manifest.yaml`
— which is plain YAML and Markdown read by
`dotnet/services/api/AgenticSupportGuide.Api/FoundryAgents/RoleDefinitions.cs`.

Module 3 continues with samples 5 to 7, which are about workflows.

## Which orchestration pattern is this?

Agent Framework ships five multi-agent patterns. This workshop uses one of
them. Which one, and why not the others, is in
[docs/orchestration-patterns.md](../../docs/orchestration-patterns.md).

## What each sample does NOT do

Every file is missing the things a real service needs: no
retries, no timeouts, no schema validation, no telemetry, no dealer group
isolation. That is the point. You will meet each of those in a later module,
at the moment it becomes necessary, so you can see what it cost to add.

## Related resources

Two steps of the Microsoft path are left out, because neither is needed to
understand this repo. Read them when you want them:

- [Memory and persistence](https://learn.microsoft.com/agent-framework/get-started/memory?pivots=programming-language-csharp)
  — sample 3 covers conversation history within one process. Persisting that
  across restarts, and long-term memory as distinct from RAG, is its own
  topic.
- [Agent Harness](https://learn.microsoft.com/agent-framework/get-started/harness?pivots=programming-language-csharp)
  — a runner for agents. Unrelated to the evaluation harness in this repo,
  despite the similar name.

Also worth reading alongside these samples:
[agent concepts](https://learn.microsoft.com/agent-framework/concepts/agents/?pivots=programming-language-csharp),
[custom agents](https://learn.microsoft.com/agent-framework/concepts/agents/custom-agents?pivots=programming-language-csharp),
and [agent safety](https://learn.microsoft.com/agent-framework/concepts/agents/safety).

## Check yourself

- [ ] All four samples ran and printed an answer.
- [ ] You changed an instruction in sample 1 and saw the answer change.
- [ ] You can name the line in sample 2 that makes a C# method callable
      by the model.
- [ ] You can explain why sample 3 answers a follow-up question and sample 1
      cannot.
- [ ] You can point at where sample 4 puts the retrieved evidence.

Next: [Module 3 — Workflows](module-3-workflows.md)
