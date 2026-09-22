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
shape where the caller sends a request and the server streams back a sequence
of typed events rather than one JSON body. Streaming is why the handler is an
async generator that `yield`s instead of a function that returns.

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

- [hosted/support-explainer/main.py](../hosted/support-explainer/main.py) —
  the Responses-protocol server
- [hosted/support-explainer/safety.py](../hosted/support-explainer/safety.py) —
  input bounds and the output gate, kept separate so it is unit-testable
  without booting the server

The server itself is small:

```python
app = ResponsesAgentServerHost()


@app.response_handler
async def handle(request, context, cancellation_signal):
    question = extract_question(request)
    if not question:
        answer = "Ask a question about dealership support practice."
    else:
        answer = gate(await _answer(question))
    async for event in TextResponse(context, request, text=answer):
        yield event
```

`ResponsesAgentServerHost` is the server; `@app.response_handler` registers
the one function it calls per request. `cancellation_signal` is how the host
tells you the caller hung up — a long-running handler should check it rather
than finish work nobody is waiting for. This one answers in a single model
call, so it does not.

Four things to notice before you deploy:

- **`request` is a plain `dict`, not an object.** `getattr(request, "input")`
  returns `None`, and your agent silently answers nothing useful. This cost a
  real deploy cycle to find. `extract_question` handles the dict shape.
- **This endpoint does its own safety work.** It never reaches the API's
  coordinator or validator agent, so `safety.py` bounds its input,
  wraps it as untrusted data, and gates the output. A hosted agent is a new
  trust boundary, not just a new deployment target, so the fencing has to be
  rebuilt here from scratch.
- **Instructions and the shared helpers are not duplicated by hand.** The publish
  script composes instructions from the same
  [agents/support-explainer/agent.md](../agents/support-explainer/agent.md)
  the Module 4 prompt agent uses, and bundles the *same*
  [services/api/app/agents/shared/prompt_blocks.py](../services/api/app/agents/shared/prompt_blocks.py)
  and
  [services/api/app/agents/shared/determinations.py](../services/api/app/agents/shared/determinations.py)
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
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <your-alias>
```

```
Agent name : asg-hosted-explainer-<your-alias>
Runtime    : python_3_13
Entrypoint : python main.py
Protocol   : responses v1.0.0
Resources  : cpu=1 memory=2Gi
Zip        : 10,418 bytes, sha256=46e69cf6f713cc2b...
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

## 3. Deploy

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <your-alias> --apply
```

```
Uploading and starting remote build...
Upload took 24s. Version: 1
  [   0s] creating
  [  41s] active
```

The first deploy is the slow one. That poll output is Foundry installing your
`requirements.txt` and building an image — a **remote build**, meaning the
dependency resolution happens on Azure's builders against your uploaded
source. A dependency that resolves on your laptop but not there fails here,
and step 4 is where you find out.

In the portal it appears alongside your prompt agents, but typed `hosted`:

![The hosted agent page showing Version 1, Kind hosted, and tabs for
Playground, Details, Traces, Monitor, Evaluation and
Optimize.](images/module-5-hosted-agent.png)

## 4. Check what the tooling tells you

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <your-alias> --status
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

```powershell
Measure-Command {
  .\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <your-alias> --apply
}
```

Reference numbers for this agent — one file, four dependencies:

| | Cold | Warm |
| --- | --- | --- |
| Upload | 24s | 4-5s |
| Remote build | ~41s | ~41s |
| **Change to live** | | **~49s** |

Compare against Module 4. Editing a prompt agent's instructions and
republishing takes a couple of seconds. Editing hosted agent code takes ~49
seconds — and this is a *small* app. More dependencies, longer build.

**Hosted-agent changes require a remote build.** Hosting costs you a build on every change. You
pay it for custom dependencies, private network access, and a dedicated
identity. If you do not need those, do not pay it.

## 6. Find its identity, and grant it access

Read the identity from the portal first: open the agent and use
**Endpoint & IDs → View details**. It has a principal ID that is **not
yours**:

```
Agent    : asg-hosted-explainer-<your-alias>
Identity : <a GUID that is your agent's, not yours>
```

Freshly deployed it holds **no permissions at all**, and cannot call the
model until someone grants it access. Do this one in the portal — the IAM
blade is where you will be asked to justify a grant, and seeing the agent's
principal appear in a role assignment list is the lesson:
1. Open your **AI Services account** → **Access control (IAM)**.
2. **Add → Add role assignment**.
3. Role: **Cognitive Services OpenAI User**.
4. Members: select **User, group, or service principal**, and search for the
   principal ID you just read from **Endpoint & IDs**. It resolves to the
   agent, not to you.
5. Review and assign.

The same grant from a shell, once you know which role you need:

```powershell
az role assignment create `
  --assignee-object-id <principal_id> `
  --assignee-principal-type ServicePrincipal `
  --role "Cognitive Services OpenAI User" `
  --scope <ai-services-account-resource-id>
```

Same three parts as the Terraform in Module 0 — a principal, a role
definition, and a scope. The difference is the principal: this one is a
**service principal**, the identity object that represents a workload rather
than a person. `Cognitive Services OpenAI User` permits inference calls on
the AI Services account and nothing else.

This is what hosting buys you. You can grant *this agent* access to a
specific database and audit what *this agent* did, instead of every agent
sharing one identity. Prompt agents cannot do that — they run under the
project's identity, so there is nothing to grant to.

With the role assigned, ask it something:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\invoke_hosted_agent.py --suffix <your-alias>
```

Role assignments take a minute or two to propagate. If this returns an
authorisation error, wait and retry before changing anything.

## 7. How rollback works

Every deploy is a retained **version**, and traffic reaches versions by rule
rather than by whichever is newest. Look at what you have:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <your-alias> --status
```

The agent's endpoint pins `@latest` at 100%:

```json
"version_selection_rules": [
  {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": 100}
]
```

`@latest` is a moving alias, not a version number: it resolves to whatever
you published most recently. `traffic_percentage` is the share of incoming
requests that rule takes, so a list of rules whose percentages sum to 100
describes the whole routing table.

Rolling back means pointing that at a specific version instead of `@latest`,
which is what `--rollback <version>` does:

```
asg-hosted-explainer-<your-alias>: 100% of traffic now pinned to v1.
```

**Notice what that does not do: build anything.** The version is already
there, so recovery is a routing change measured in seconds rather than the
~49 seconds a deploy costs. That property — rollback must not require a
build — is worth taking to a production design, and it is exactly what the
App Service deployment in Module 1 does *not* have.

The script also refuses to pin traffic to a version whose build failed:

```
v2 is 'failed'; refusing to send traffic to it.
```

That guard matters because of step 4: the version list will happily show you a
failed version as though it were a candidate.

The same mechanism splits traffic to **canary** a change — two rules with
percentages that sum to 100, so a new version takes a small share of real
traffic while you watch it, instead of all of it at once.

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
[.github/workflows/deploy.yml](../.github/workflows/deploy.yml):
`workflow_dispatch` only, federated credentials, publish, `--status`, then a
real question through the agent as a smoke test. The agent's identity needs
its own role assignment, as section 6 showed — the pipeline's service
principal deploying the agent is not the same principal as the agent calling
the model.

---

## Notes on timing

- Deploys are ~49s each, so the edit-deploy-test loop in this module is
  comfortably hands-on.
- Each learner deploys into their own project, but the remote build service
  is Azure's. **Concurrency at 30 simultaneous builds has not been
  measured.** If a whole room hits step 3 at the same moment and builds
  queue, that is why — stagger it rather than assuming something is broken.
- Step 6 needs permission to create a role assignment on your AI Services
  account. You already have it if you ran Module 0 as `Owner` or
  `User Access Administrator`, which is why that is on the
  [prerequisites](README.md#prerequisites) list.

## Check yourself

- [ ] You deployed and versioned your own agent.
- [ ] You can explain why rollback here does not require a build.
- [ ] You can state your change-to-live time from measurement, not guesswork.
- [ ] You found your agent's principal ID and know why it needed a role.
- [ ] You can explain why `list_versions` should not be trusted.
- [ ] You can explain how the output gate withholds a determination.

Next: [Module 6 — Ground it with RAG](module-6-rag.md)
