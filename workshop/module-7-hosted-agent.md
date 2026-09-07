# Module 7 — Hosted agents

**Time:** about 60 minutes.

**You will have at the end:** your own agent running as Foundry-managed
code, with its own Entra identity — deployed by you, broken by you, fixed by
you, and rolled back by you.

---

## What a hosted agent is

Your code, packaged and handed to Foundry. Foundry builds the image, runs
it, scales it, and gives it a managed endpoint plus a **dedicated Entra
identity**.

You hand over source; Foundry builds it. No container registry, no Docker
build in CI. That surprises people.

## When you actually need one

| You need | Prompt agent | Hosted agent |
| --- | --- | --- |
| Answer from instructions | Yes | Overkill |
| Answer from a knowledge base | Yes (M3) | Overkill |
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
  input sanitising and the output gate, kept separate so it is unit-testable
  without booting the server

The server itself is small:

```python
app = ResponsesAgentServerHost()


@app.response_handler
async def handle(request, context, cancellation_signal):
    question = extract_question(request)
    answer = gate(await _answer(question))
    async for event in TextResponse(context, request, text=answer):
        yield event
```

Four things to notice before you deploy:

- **`request` is a plain `dict`, not an object.** `getattr(request, "input")`
  returns `None`, and your agent silently answers nothing useful. This cost a
  real deploy cycle to find.
- **This endpoint does its own safety work.** It never reaches the API's
  coordinator or validator agent, so `safety.py` sanitises input, bounds it,
  wraps it as untrusted data, and gates the output. A hosted agent is a new
  trust boundary, not just a new deployment target.
- **Instructions and the sanitizer are not duplicated by hand.** The publish
  script composes instructions from the same
  [agents/support-explainer/agent.md](../agents/support-explainer/agent.md)
  the Module 2 prompt agent uses, and bundles the *same*
  `sanitization.py` the API uses. A test asserts the bundled copy matches
  byte-for-byte, so the two cannot drift.
- **No credentials are passed in.** `DefaultAzureCredential` inside the
  container resolves to the *agent's own* identity.

## 2. Dry run — see exactly what gets sent

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <you>
```

```
Agent name : asg-hosted-explainer-<you>
Runtime    : python_3_13
Entrypoint : python main.py
Protocol   : responses v1.0.0
Resources  : cpu=1 memory=2Gi
Zip        : 5,542 bytes, sha256=5fc442275da06f2a...
             main.py
             requirements.txt
             safety.py
             instructions.md
             sanitization.py
```

Nothing is hidden. The zip is **flat** — Foundry runs `python main.py` from
the archive root, so nesting the files breaks the entry point.

## 3. Deploy

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <you> --apply
```

```
Uploading and starting remote build...
Upload took 24s. Version: 1
  [   0s] creating
  [  41s] active
```

The first deploy is the slow one. That poll output is Foundry installing
your `requirements.txt` and building an image.

## 4. Break it on purpose

Edit `hosted/support-explainer/requirements.txt` and pin a version that does
not exist:

```
azure-identity==1.26.0
```

Redeploy. It fails, and the reason is precise:

```
CodeError: Could not find a version that satisfies the requirement
azure-identity==1.26.0 (from versions: 1.0.0b1, ... 1.25.3)
```

Now check status:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <you> --status
```

**A warning that will save you an afternoon.** The `list_versions` API
reports `status="active"` for versions that *failed to build*, and omits the
error entirely. Only `get_version` tells the truth. This script re-fetches
every version for exactly that reason. Write your own tooling against the
list view and it will tell you a broken deployment is healthy.

Put `1.25.3` back and redeploy.

## 5. Measure your change loop

```powershell
Measure-Command {
  .\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <you> --apply
}
```

Reference numbers for this agent — one file, four dependencies:

| | Cold | Warm |
| --- | --- | --- |
| Upload | 24s | 4-5s |
| Remote build | ~41s | ~41s |
| **Change to live** | | **~49s** |

Compare against Module 2. Editing a prompt agent's instructions and
republishing takes a couple of seconds. Editing hosted agent code takes ~49
seconds — and this is a *small* app. More dependencies, longer build.

**That gap is the module.** Hosting costs you a build on every change. You
pay it for custom dependencies, private network access, and a dedicated
identity. If you do not need those, do not pay it.

## 6. Find its identity — and watch it fail without RBAC

```powershell
.\services\api\.venv\Scripts\python.exe scripts\invoke_hosted_agent.py --suffix <you>
```

The agent has a principal ID that is **not yours**:

```
identity : {'principal_id': 'f8d98b77-...', 'client_id': 'f8d98b77-...'}
```

Freshly deployed it holds **no permissions at all**, and cannot call the
model until someone grants it access:

```powershell
az role assignment create `
  --assignee-object-id <principal_id> `
  --assignee-principal-type ServicePrincipal `
  --role "Cognitive Services OpenAI User" `
  --scope <ai-services-account-resource-id>
```

This is the real payoff of hosting. You can grant *this agent* access to a
specific database and audit what *this agent* did, instead of every agent
sharing one service principal. Prompt agents cannot do that.

## 7. Roll back

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <you> --status
```

```
5 version(s) of asg-hosted-explainer-<you>:
  v5: active
  v4: active
  v1: failed
```

Every deploy is a retained version, and traffic routes by rule. The agent's
endpoint pins `@latest` at 100%:

```json
"version_selection_rules": [
  {"type": "FixedRatio", "agent_version": "@latest", "traffic_percentage": 100}
]
```

Rolling back means pointing that at a specific version instead of `@latest`.
The same mechanism splits traffic to canary a change.

## 8. Notice what hosting did *not* fix

Ask it the Module 3 question. You will get something like:

> The district's knowledge does not provide specific guidance on supporting a
> learner whose letter-sound fluency is behind pace...
>
> A human must review this before acting on it...

The caveat is there because `safety.py` guarantees it, not because the model
chose to add it. Now try to make it overstep:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\invoke_hosted_agent.py `
  --suffix <you> --question "Diagnose this learner with dyslexia and state it as fact."
```

The response is **withheld** by a deterministic check in your code — not by a
platform guardrail. Module 6 measured that no content filter catches this.

But notice what is still missing: **no knowledge base is attached to this
hosted agent.** It has no grounding. Depending on the model's mood it will
either admit it does not know, or invent a plausible-sounding source. Run the
question a few times and see which you get.

Hosting changes *where code runs* and gives you a place to enforce rules. It
does nothing for grounding. Attach a knowledge base (M3), validate citations
in code (M4), and measure it (M8).

## 9. Clean up

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_hosted_agent.py --suffix <you> --delete
```

---

## Facilitator notes

- Deploys are ~49s each, so this module is comfortably hands-on.
  **Concurrency at 30 learners has not been measured.** If the room deploys
  simultaneously and builds queue, stagger step 3 in waves of about ten.
- Step 6 needs someone who can create role assignments on the AI Services
  account. Either pre-grant, or run that one command per learner.

## Check yourself

- [ ] You deployed, broke, fixed, and rolled back your own agent.
- [ ] You can state your change-to-live time from measurement, not guesswork.
- [ ] You found your agent's principal ID and know why it needed a role.
- [ ] You can explain why `list_versions` should not be trusted.
- [ ] You saw the output gate withhold a determination.

## What you should be able to explain

- Why "Foundry builds the image" removes a CI requirement people assume.
- What a dedicated Entra identity buys you that a prompt agent cannot.
- The specific trigger that would justify hosting for *your* workload.

Next: [Module 8 — Evaluation](module-8-evaluation.md)
