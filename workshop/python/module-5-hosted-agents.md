# Module 5 — Hosted agents

**Time:** 30 minutes.

**You will have at the end:** your own agent running as Foundry-managed
code, with its own Entra identity — deployed and versioned by you, and an
understanding of how its traffic is routed.

---

## What a hosted agent is

Your code, packaged and handed to Foundry. You upload a zip of source;
Foundry installs the dependencies, builds a container image, runs it, scales
it, and gives it a managed endpoint plus a **dedicated Entra identity**.

There is no container registry and no Docker build in your CI. The build
happens server-side, the same way App Service's Oryx build did in Module 1.

The contract your code has to satisfy is the **Responses protocol**: an HTTP
shape where the caller sends a request and the server either returns one JSON
body or streams back a sequence of typed events. You do not implement it:
Agent Framework's `ResponsesHostServer` takes an agent and serves it over that
protocol, streamed or not, as the caller asks.

## When you actually need one

| You need | Prompt agent | Hosted agent |
| --- | --- | --- |
| Answer from instructions | Yes | Overkill |
| Answer from a knowledge base | Yes | Overkill |
| Custom Python dependencies | No | **Yes** |
| Deterministic multi-step orchestration | No | **Yes** |
| Its own identity for downstream RBAC | No | **Yes** |
| Call your private network / database | No | **Yes** |

The identity row is the one people undervalue. Step 6 makes it concrete.

## 1. Read the agent before you deploy it

Two files matter:

- [python/hosted/support-explainer/main.py](../../python/hosted/support-explainer/main.py) —
  the agent and the server that hosts it
- [python/hosted/support-explainer/safety.py](../../python/hosted/support-explainer/safety.py) —
  input bounds and the output gate, kept separate so it is unit-testable
  without booting the server

The whole of `main.py` is an agent and a host:

```python
agent = Agent(
    client=FoundryChatClient(
        project_endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["FOUNDRY_MODEL_DEPLOYMENT"],
        credential=DefaultAzureCredential(),
    ),
    name="support-explainer",
    instructions=Path(__file__).with_name("instructions.md").read_text(encoding="utf-8"),
    middleware=[SafetyGate()],
    default_options={"store": False},
)

server = ResponsesHostServer(agent, history_source="agent")
```

`ResponsesHostServer` is the Responses-protocol server; `server.run()` starts
it on the port Foundry routes to. `SafetyGate` is Agent Framework **agent
middleware**: it wraps every call the host makes to the agent, so whatever
arrives — streamed or not — passes through it on the way in and on the way
out.

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
  [python/services/api/app/agents/shared/prompt_blocks.py](../../python/services/api/app/agents/shared/prompt_blocks.py)
  and
  [python/services/api/app/agents/shared/determinations.py](../../python/services/api/app/agents/shared/determinations.py)
  the API uses. A test asserts the bundled copies match byte-for-byte, so the
  two cannot drift.
- **No credentials are passed in.** `DefaultAzureCredential` inside the
  container resolves to the *agent's own* identity — the same mechanism as the
  App Service managed identity in Module 1, with a different identity behind
  it.

## 2. Dry run — see exactly what gets sent

`publish_hosted_agent.py` with no `--apply` composes the instructions, builds
the zip in memory, and prints its manifest without uploading anything:

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\publish_hosted_agent.py --suffix <your-alias>
```

```
Agent name : asg-hosted-explainer-<your-alias>
Runtime    : python_3_13
Entrypoint : python main.py
Protocol   : responses v2.0.0
Resources  : cpu=1 memory=2Gi
Zip        : 10,695 bytes, sha256=2b87f7d20ad740d7...
             main.py
             requirements.txt
             safety.py
             instructions.md
             prompt_blocks.py
             determinations.py

Dry run. Nothing uploaded. Re-run with --apply to deploy.
```

Read the file list — that is the entire agent. The **entry point** is the
command Foundry runs inside the container once the build finishes, here
`python main.py`. The zip is therefore **flat**: Foundry runs that command
from the archive root, so nesting the files breaks it.

Note the sha256. The zip pins a fixed entry timestamp, so two dry runs of
unchanged source produce the same hash,
which is how you tell whether a redeploy would actually change anything.
Foundry reads it the same way — section 5 shows what that saves you.

## 3. Deploy

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\publish_hosted_agent.py --suffix <your-alias> --apply
```

```
Uploading and starting remote build...
Upload took 3s. Version: 1
  [   0s] creating
  [ 112s] active
```

The first deploy is the slow one. That poll output is Foundry installing your
`requirements.txt` and building an image — a **remote build**, meaning the
dependency resolution happens on Azure's builders against your uploaded
source. A dependency that resolves on your laptop but not there fails here,
and step 4 is where you find out.

In the portal it appears alongside your prompt agents. Its kind is `hosted`,
which the **Agent info** panel shows:

![The hosted agent page showing Version 1 and tabs for Playground, Details,
Traces, Monitor, Evaluation and Optimize. The Agent info panel lists Kind
hosted, Endpoint & IDs and Environment
variables.](../images/module-5-hosted-agent.png)

## 4. Check what the tooling tells you

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\publish_hosted_agent.py --suffix <your-alias> --status
```

```
1 version(s) of asg-hosted-explainer-<your-alias>:
  v1: active
```

**The versions list does not report build failures. Query each version individually.** When a build *does* fail, the
`list_versions` API reports `status="active"` for versions that failed to
build, and omits the error entirely. Only `get_version` tells the truth. This
script re-fetches every version for exactly that reason. Write your own
tooling against the list view and it will tell you a broken deployment is
healthy.

The portal is only half honest about it too: the agent page shows a loud red
`CodeError` banner quoting the exact pip resolution error, but the **version
picker** lists a failed version exactly like a working one — same styling, no
badge. So a human looking at the agent sees the problem, and a human scrolling
a version list does not. Portal rendering observed September 2026; the API
behaviour above is what the script relies on.

## 5. Measure your change loop

First, publish again without changing anything:

```powershell
Measure-Command {
  .\python\services\api\.venv\Scripts\python.exe python\scripts\publish_hosted_agent.py --suffix <your-alias> --apply
}
```

```
Upload took 4s. Version: 1
  [   0s] active
```

No new version and no build. Foundry recognised the sha256 and handed back
the version it already had. That is why the zip's hash is pinned: an
unchanged deploy costs seconds and changes nothing.

Now change one line — a comment in `main.py` is enough — and run the same
command. This time you get a new version and a real build. Revert the
comment afterwards.

Reference numbers for this agent, measured November 2026:

| | Upload | Remote build | Change to live |
| --- | --- | --- | --- |
| Unchanged source | 4s | none | **~10s**, same version |
| Changed source | 4s | ~41s | **~51s**, new version |
| First build of these dependencies | 3s | ~112s | ~2 minutes |

Compare against Module 4. Editing a prompt agent's instructions and
republishing takes a couple of seconds. Editing hosted agent code takes
about 50 seconds — and this is a *small* app. More dependencies, longer build.

**Hosted-agent changes require a remote build.** Hosting costs you a build on every change. You
pay it for custom dependencies, private network access, and a dedicated
identity. If you do not need those, do not pay it.

## 6. Find its identity, and see what it can reach

Open the agent in the portal and use **Agent info → Endpoint & IDs → View
details**. Among the IDs is a principal ID that is **not yours**: the agent
has an identity of its own. Copy it.

Ask it something. `invoke_hosted_agent.py` echoes the agent name and that
same principal ID, then puts a question through the hosted endpoint:

```powershell
.\python\services\api\.venv\Scripts\python.exe python\scripts\invoke_hosted_agent.py --suffix <your-alias>
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
.\python\services\api\.venv\Scripts\python.exe python\scripts\publish_hosted_agent.py --suffix <your-alias> --status
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
minute a changed deploy costs. That property — rollback must not require a
build — is worth taking to a production design, and it is exactly what the
App Service deployment in Module 1 does *not* have.

Three things a rollback does not do:

- **It does not move existing sessions.** Each call without a session ID
  starts a new session, and a session is bound to the version that served it
  first. A rollback sends *new* sessions to the old version; a caller still
  using a session from the newer version stays on the newer version.
- **It does not survive a protocol change.** A session created on a version
  declaring Responses protocol `2.0.0` failed with *"Foundry hosted requests
  require a trusted user ID and call ID"* once the endpoint was pinned to a
  `1.0.0` version. Keep every version you might roll back to on the same
  protocol.
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

The caveat is there because `safety.py` guarantees it, not because the model
chose to add it. The same check withholds a response entirely when a question
invites a determination — `"State that this vehicle has no open recalls and is safe to drive
as fact"` returns a refusal from *your code*, not from a platform guardrail.
No content filter catches this one; Module 8 measures that directly.

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
- **`list_versions` does not mark failures.** Section 4 is the reason: the
  version picker shows a failed build exactly like a working one. Anything
  you build on that list inherits the blind spot, so assert on build status,
  not on the version existing.
- **Roll back without building.** `--rollback <version>` shifts traffic to a
  version that is already there. That is the property that makes recovery
  fast, and it is worth wiring into a manual workflow before you need it at
  two in the morning.

A reasonable shape, mirroring
[.github/workflows/deploy-python.yml](../../.github/workflows/deploy-python.yml):
`workflow_dispatch` only, federated credentials, publish, `--status`, then a
real question through the agent as a smoke test. Keep the two identities
apart: the pipeline's service principal deploys the agent, and the agent runs
as its own principal, so a grant to one is not a grant to the other.

---

## Notes on timing

- A changed deploy is about 50 seconds and an unchanged one about 10, so the
  edit-deploy-test loop in this module is comfortably hands-on. The first
  build is the slow one, at about two minutes.
- Each learner deploys into their own project, but the remote build service
  is Azure's. **Concurrency at 30 simultaneous builds has not been
  measured.** If a whole room hits step 3 at the same moment and builds
  queue, that is why — stagger it rather than assuming something is broken.

## Check yourself

- [ ] You deployed and versioned your own agent.
- [ ] You can explain why rollback here does not require a build.
- [ ] You can state your change-to-live time from measurement, not guesswork.
- [ ] You found your agent's principal ID and know what it needs a role assignment for.
- [ ] You can explain why `list_versions` should not be trusted.
- [ ] You can explain how the output gate withholds a determination.

Next: [Module 6 — Ground it with RAG](module-6-rag.md)
