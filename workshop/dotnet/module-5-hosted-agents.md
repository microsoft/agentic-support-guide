# Module 5 — Hosted agents

**Time:** 30 minutes.

**You will have at the end:** your own agent running as Foundry-managed
code, with its own Entra identity — deployed and versioned by you, and an
understanding of how its traffic is routed.

---

## What a hosted agent is

Your code, packaged and handed to Foundry. You upload a zip of source;
Foundry restores the dependencies, builds it into a container image, runs it,
scales it, and gives it a managed endpoint plus a **dedicated Entra
identity**.

There is no container registry and no Docker build in your CI. The build
happens server-side — unlike Module 1, where you published the API on your
own machine and App Service only ran the result.

The contract your code has to satisfy is the **Responses protocol**: an HTTP
shape where the caller sends a request and the server either returns one JSON
body or streams back a sequence of typed events. You do not implement it:
Agent Framework's Foundry hosting takes an agent and serves it over that
protocol, streamed or not, as the caller asks.

## When you actually need one

| You need | Prompt agent | Hosted agent |
| --- | --- | --- |
| Answer from instructions | Yes | Overkill |
| Answer from a knowledge base | Yes | Overkill |
| Custom NuGet dependencies | No | **Yes** |
| Deterministic multi-step orchestration | No | **Yes** |
| Its own identity for downstream RBAC | No | **Yes** |
| Call your private network / database | No | **Yes** |

The identity row is the one people undervalue. Step 6 makes it concrete.

## 1. Read the agent before you deploy it

Two files matter:

- [dotnet/hosted/support-explainer/Program.cs](../../dotnet/hosted/support-explainer/Program.cs) —
  the agent and the server that hosts it
- [dotnet/hosted/support-explainer/SafetyGate.cs](../../dotnet/hosted/support-explainer/SafetyGate.cs) —
  input bounds and the output gate, kept separate so it is unit-testable
  without booting the server

The whole of `Program.cs` is an agent and a host:

```csharp
AIAgent agent = SafetyGate.Around(project.AsAIAgent(new ChatClientAgentOptions
{
    Name = "support-explainer",
    ChatOptions = new ChatOptions
    {
        ModelId = Required("FOUNDRY_MODEL_DEPLOYMENT"),
        Instructions = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "instructions.md")),
        // The model service keeps nothing either.
        RawRepresentationFactory = _ => new CreateResponseOptions { StoredOutputEnabled = false },
    },
}));

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://0.0.0.0:{Environment.GetEnvironmentVariable("PORT") ?? "8088"}");
builder.AddFoundryResponses(agent);

var app = builder.Build();
app.MapFoundryResponses();
app.Run();
```

`AddFoundryResponses` registers Agent Framework's Responses-protocol host for
the agent, and `MapFoundryResponses` serves it on the port Foundry routes to.
`SafetyGate.Around` is Agent Framework **agent middleware** — `AsBuilder().Use(...)`
with a handler for plain and for streamed runs — so whatever arrives passes
through it on the way in and on the way out.

Things to notice before you deploy:

- **This endpoint does its own safety work.** It never reaches the API's
  coordinator or validator agent, so `SafetyGate` bounds its input, wraps it
  as untrusted data, and gates the output. A hosted agent is a new trust
  boundary, not just a new deployment target, so the fencing has to be
  rebuilt here from scratch.
- **Nothing carries over between requests.** The gate hands the agent only
  this request's question, with no session and none of the caller's options.
  An earlier turn, a caller's own `instructions` or a different model never
  reach the model. An empty question gets a fixed reply and no model call at
  all.
- **A streamed answer is held until it is whole.** A gate that has seen half
  an answer cannot withhold the other half, so for a streamed call the gate
  buffers the answer, checks it, and releases the result in one piece.
  Streaming still works; the text simply arrives at once.
- **Instructions and the shared helpers are not duplicated by hand.** The publish
  script composes instructions from the same
  [agents/support-explainer/agent.md](../../agents/support-explainer/agent.md)
  the Module 4 prompt agent uses, and bundles the *same*
  [PromptBlocks.cs](../../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/PromptBlocks.cs)
  and
  [Determinations.cs](../../dotnet/services/api/AgenticSupportGuide.Api/Agents/Shared/Determinations.cs)
  the API uses. A test asserts the bundled copies match byte-for-byte, so the
  two cannot drift.
- **No credentials are passed in.** `DefaultAzureCredential` inside the
  container resolves to the *agent's own* identity — the same mechanism as the
  App Service managed identity in Module 1, with a different identity behind
  it.
- **Registered on the builder, not on `builder.Services`.** In Foundry the
  host binds its storage identities from configuration, and the
  `builder.AddFoundryResponses(agent)` form is the one that does it. The
  `services` overload builds and runs locally, then fails to start once
  deployed.

## 2. Dry run — see exactly what gets sent

`publish_hosted_agent.cs` with no `--apply` composes the instructions, stages
the files, has the Foundry SDK build the exact zip it would upload, and prints
its manifest without uploading anything:

```powershell
dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias>
```

```
Agent name : asg-hosted-explainer-<your-alias>
Runtime    : dotnet_10
Entrypoint : dotnet SupportExplainer.dll
Protocol   : responses v2.0.0
Resources  : cpu=1 memory=2Gi
Zip        : 16,356 bytes, sha256=65d934f41ae1962d...
             Determinations.cs
             Directory.Build.props
             Directory.Packages.props
             instructions.md
             Program.cs
             PromptBlocks.cs
             PyText.cs
             SafetyGate.cs
             SupportExplainer.csproj

Dry run. Nothing uploaded. Re-run with --apply to deploy.
```

Read the file list — that is the entire agent: the project, its source, the
shared files from the API, and the two `Directory.*.props` files that pin the
package versions. The **entry point** is the command Foundry runs inside the
container once the build finishes, here `dotnet SupportExplainer.dll`. The
zip is **flat**: the builder finds the project file at the archive root, and
the shared files sit beside it rather than in the API folder the project links
them from locally.

Note the sha256. Every file goes in with a fixed timestamp, so two dry runs
of unchanged source produce the same hash, which is how you tell whether a
redeploy would actually change anything. That is also why the zip is flat:
the SDK stamps folder entries with the current time, so a nested zip would
hash differently on every run. Foundry reads the hash the same way —
section 5 shows what that saves you.

## 3. Deploy

```powershell
dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --apply
```

```
Uploading and starting remote build...
Upload took 6s. Version: 1
  [   1s] creating
  [  34s] active

Build finished in 34s. Agent is active.
```

That poll output is Foundry restoring your NuGet packages and building an
image — a **remote build**, meaning the restore and compile happen on Azure's
builders against your uploaded source. A dependency that resolves on your
laptop but not there fails here, and step 4 is where you find out.

In the portal it appears alongside your prompt agents. Its kind is `hosted`,
which the **Agent info** panel shows:

![The hosted agent page showing Version 1 and tabs for Playground, Details,
Traces, Monitor, Evaluation and Optimize. The Agent info panel lists Kind
hosted, Endpoint & IDs and Environment
variables.](../images/module-5-hosted-agent.png)

## 4. Check what the tooling tells you

```powershell
dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --status
```

```
1 version(s) of asg-hosted-explainer-<your-alias>:
  v1: active
```

**The versions list does not report build failures. Query each version individually.** When a build *does* fail, the
list-versions API reports `status="active"` for versions that failed to
build, and omits the error entirely. Only get-version tells the truth. This
script re-fetches every version for exactly that reason. Write your own
tooling against the list view and it will tell you a broken deployment is
healthy.

The portal is only half honest about it too: the agent page shows a loud red
`CodeError` banner quoting the exact build error, but the **version
picker** lists a failed version exactly like a working one — same styling, no
badge. So a human looking at the agent sees the problem, and a human scrolling
a version list does not. Portal rendering observed September 2026; the API
behaviour above is what the script relies on.

## 5. Measure your change loop

First, publish again without changing anything:

```powershell
Measure-Command {
  dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --apply
}
```

```
Upload took 2s. Version: 1
  [   1s] active
```

No new version and no build. Foundry recognised the sha256 and handed back
the version it already had. That is why the zip's hash is pinned: an
unchanged deploy costs seconds and changes nothing.

Now change one line — a comment in `Program.cs` is enough — and run the same
command. This time you get a new version and a real build. Revert the
comment afterwards.

Reference numbers for this agent, measured November 2026. "Change to live"
is the whole command, including `dotnet run` compiling the script:

| | Upload | Remote build | Change to live |
| --- | --- | --- | --- |
| Unchanged source | 2s | none | **~6s**, same version |
| Changed source | 2s | ~34s | **~39s**, new version |
| First build of a new agent | 6s | ~34s | ~45s |

Compare against Module 4. Editing a prompt agent's instructions and
republishing takes a couple of seconds. Editing hosted agent code takes
about 40 seconds — and this is a *small* app. More dependencies, longer build.

**Hosted-agent changes require a remote build.** Hosting costs you a build on every change. You
pay it for custom dependencies, private network access, and a dedicated
identity. If you do not need those, do not pay it.

## 6. Find its identity, and see what it can reach

Open the agent in the portal and use **Agent info → Endpoint & IDs → View
details**. Among the IDs is a principal ID that is **not yours**: the agent
has an identity of its own. Copy it.

Ask it something. `invoke_hosted_agent.cs` echoes the agent name and that
same principal ID, then puts a question through the hosted endpoint:

```powershell
dotnet run dotnet/scripts/invoke_hosted_agent.cs -- --suffix <your-alias>
```

It answers. Now look at what that identity has been granted:

```powershell
az role assignment list --assignee <principal_id> --all -o table
```

Nothing. Foundry lets a hosted agent call the models in its own project
without a role assignment. Anything outside the project is different — a
storage account, a database, another project's models. Each of those needs a
role assignment for *this* principal, made the same way Module 0's Terraform
made yours:

```powershell
az role assignment create `
  --assignee-object-id <principal_id> `
  --assignee-principal-type ServicePrincipal `
  --role "<role>" `
  --scope <resource-id>
```

Same three parts — a principal, a role definition, and a scope. The
difference is the principal: this one is a **service principal**, the
identity object that represents a workload rather than a person.

This is what hosting buys you. You can grant *this agent* access to a
specific database and audit what *this agent* did, instead of every agent
sharing one identity. Prompt agents cannot do that — they run under the
project's identity, so there is nothing to grant to.

## 7. How rollback works

Every deploy is a retained **version**, and traffic reaches versions by rule
rather than by whichever is newest. Look at what you have:

```powershell
dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --status
```

The agent's endpoint pins `@latest` at 100%:

```json
"version_selection_rules": [
  {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": 100}
]
```

`@latest` is a moving alias, not a version number: it resolves to whatever
you published most recently. The endpoint sends all of its traffic to one
version. The rules are a list, but splitting traffic between versions is not
supported: one rule, at 100%.

Rolling back means pointing that rule at a specific version instead of
`@latest`, which is what `--rollback <version>` does:

```
asg-hosted-explainer-<your-alias>: 100% of traffic now pinned to v1.
```

**Notice what that does not do: build anything.** The version is already
there, so recovery is a routing change measured in seconds rather than the
forty seconds a changed deploy costs. That property — rollback must not require a
build — is worth taking to a production design, and it is exactly what the
App Service deployment in Module 1 does *not* have.

Three things a rollback does not do:

- **It does not move existing sessions.** Each call without a session ID
  starts a new session, and a session is bound to the version that served it
  first. A rollback sends *new* sessions to the old version; a caller still
  using a session from the newer version stays on the newer version.
- **It does not survive a protocol change.** In this workshop's Python track,
  a session created on a version declaring Responses protocol `2.0.0` failed
  with *"Foundry hosted requests require a trusted user ID and call ID"* once
  the endpoint was pinned to a `1.0.0` version. Every version this track
  publishes declares `2.0.0`; keep every version you might roll back to on the
  same protocol.
- **It does not follow your next publish.** While the rule names a version,
  a new publish receives no traffic. Pin the newer version the same way to go
  forward again.

The script also refuses to pin traffic to a version whose build failed:

```
v2 is 'failed'; refusing to send traffic to it.
```

That guard matters because of step 4: the version list will happily show you a
failed version as though it were a candidate.

## 8. Notice what hosting did *not* fix

Ask it the same first-reply-time question you asked the prompt agent in
Module 4. You will get something like:

> The dealer group's knowledge does not provide specific guidance on supporting a
> dealership whose first-reply time has slipped past the standard...
>
> A human must review this before acting on it...

The caveat is there because `SafetyGate.cs` guarantees it, not because the
model chose to add it. The same check withholds a response entirely when a
question invites a determination — `"State that this vehicle has no open
recalls and is safe to drive as fact"` returns a refusal from *your code*, not
from a platform guardrail. No content filter catches this one; Module 8
measures that directly.

But notice what is still missing: **no knowledge base is attached to this
hosted agent.** It has no grounding. Depending on the model's mood it will
either admit it does not know, or invent a plausible-sounding source. Run the
question a few times and see which you get.

Hosting changes *where code runs* and gives you a place to enforce rules. It
does nothing for grounding. Grounding needs a knowledge base, which is
Module 6.

## 9. Optional — put the hosted agent in a pipeline

**Skip this if you are not doing CI.** Nothing later depends on it.

A hosted agent is code, so it gets the deployment problems code has. Automating
it means encoding what this module showed you:

- **The publish exit code is not the deploy result.** A build can fail
  *after* a successful upload, so a pipeline step that only checks the
  publish command will go green on a broken agent. Follow it with
  `--status` and fail on anything that is not a healthy newest version.
- **The versions list does not mark failures.** Section 4 is the reason: the
  version picker shows a failed build exactly like a working one. Anything
  you build on that list inherits the blind spot, so assert on build status,
  not on the version existing.
- **Roll back without building.** `--rollback <version>` shifts traffic to a
  version that is already there. That is the property that makes recovery
  fast, and it is worth wiring into a manual workflow before you need it at
  two in the morning.

A reasonable shape, mirroring
[.github/workflows/deploy-dotnet.yml](../../.github/workflows/deploy-dotnet.yml):
`workflow_dispatch` only, federated credentials, publish, `--status`, then a
real question through the agent as a smoke test. Keep the two identities
apart: the pipeline's service principal deploys the agent, and the agent runs
as its own principal, so a grant to one is not a grant to the other.

---

## Notes on timing

- A changed deploy is about 40 seconds and an unchanged one about 6, so the
  edit-deploy-test loop in this module is comfortably hands-on. The first
  build of a new agent measured about the same, at roughly 45 seconds.
- Each learner deploys into their own project, but the remote build service
  is Azure's. **Concurrency at 30 simultaneous builds has not been
  measured.** If a whole room hits step 3 at the same moment and builds
  queue, that is why — stagger it rather than assuming something is broken.

## Check yourself

- [ ] You deployed and versioned your own agent.
- [ ] You can explain why rollback here does not require a build.
- [ ] You can state your change-to-live time from measurement, not guesswork.
- [ ] You found your agent's principal ID and know what it needs a role assignment for.
- [ ] You can explain why the versions list should not be trusted.
- [ ] You can explain how the output gate withholds a determination.

Next: [Module 6 — Ground it with RAG](module-6-rag.md)
