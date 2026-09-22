# Module 4 — Prompt agents

**Time:** 25 minutes.

**You will have at the end:** an agent you can see, run, and version in the
Foundry portal — built from a file in this repo, with no application code
running anywhere.

---

## What a prompt agent is

A **prompt agent** is a model deployment plus instructions plus a contract,
stored in Foundry. Foundry runs it. There is no container, no web app, and
nothing of yours to keep alive.

If your agent is "answer questions about X using Y," you do not need to write
or host a service. This module shows where that ceiling is before you start
building past it.

Compare the three ways to run an agent on Foundry:

| | Prompt agent | Hosted agent | Direct API call |
| --- | --- | --- | --- |
| Where code runs | Foundry | Foundry-managed container | Your process |
| Visible in portal | Yes | Yes | No |
| Versioned | Yes | Yes | No |
| Own identity | No | Yes, dedicated Entra identity | No |
| Custom dependencies | No | Yes | Yes |
| You operate it | No | No | Yes |

Module 5 builds the hosted variant. This repo's own backend uses the third
column — it composes each role in-process and calls the model directly, which
is why a prompt edit takes effect without publishing anything.

## 1. Read the agent definition

Open [agents/support-explainer/agent.md](../agents/support-explainer/agent.md).

It is a markdown file with **YAML frontmatter** — a `---`-delimited block of
structured data at the top, followed by prose. Both halves are inputs:

- The frontmatter holds `constraints`, `safety_rules` and `grounding_rules`.
  These are not documentation. `compose_instructions` in
  [services/api/app/foundry_agents/prompt_envelope.py](../services/api/app/foundry_agents/prompt_envelope.py)
  renders them into the instruction text the model receives.
- The markdown body is the role description.

Splitting them is what lets `validate_agent_definitions.py` check that a
definition has safety rules at all. Prose in a paragraph cannot be checked;
a list under a known key can.

An earlier version of the composer used only the markdown body and silently
discarded the frontmatter. Output stayed *plausible*, so nothing looked
broken — it was simply no longer bound by the contract. If you change
`agent.md` and behaviour does not change, confirm the part you edited is
reaching the model before you start rewriting your prompt.

Now open [agents/support-explainer/manifest.yaml](../agents/support-explainer/manifest.yaml).
A **manifest** is the machine-readable half of the definition: which model
deployment to use, which schemas apply, what the agent is called.
`model_deployment_env` names an *environment variable* rather than a
deployment, which is what lets the same definition run against your
deployment and someone else's.

## 2. Validate

```powershell
.\services\api\.venv\Scripts\python.exe scripts\validate_agent_definitions.py
```

This parses the frontmatter, confirms the required keys are present, resolves
the model deployment from the environment, and hashes the composed
instructions. No network calls, so it is fast and safe to run on every edit.

Note the `instructions_hash` for `support-explainer`. It is a hash of the
*composed* instruction text — body plus the three frontmatter rule lists,
whitespace-normalised, as `compose_instructions` renders them. Change one word
in `agent.md`, re-run, and watch it change. **Undo that edit before you
continue**, so what you publish in step 5 is the definition in source control.

It is a fingerprint of the instruction text, not of the whole deployment: the
model, temperature, tools and any attached knowledge are not in it. That makes
it the right tool for "did the wording drift?" and the wrong one for "is the
deployed agent identical?"

## 3. Create it in the portal, by hand

Build the agent yourself first. The script in step 5 does the same thing in
one line, and you will not understand what that line did unless you have done
it once.

The instructions you paste are **not** the body of `agent.md` — they are the
composed form from step 2. Print the real thing:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\validate_agent_definitions.py --show-instructions support-explainer
```

Read the output next to the source file and find where the frontmatter lists
ended up. That mapping is the entire mechanism.

Copy it. Then in your Foundry project:

1. **Build → Agents → New agent.** An *agent* here is a named, versioned
   record holding instructions and a model reference. Creating one calls no
   model and costs nothing.
2. Name it `asg-support-explainer-agent-<your-alias>`. The name matters —
   Module 8 and the cleanup in Module 10 both match on it.
3. Set the model to `asg-chat` — the deployment Module 0 created, not a model
   name.
4. Paste the composed instructions.
5. **Save.** This creates version 1.

![The Foundry Agents list showing four agents. The one just created,
asg-support-explainer-agent-demo, sits above the three role agents Module 3
published, all at version 1 with a Running status and a Prompt type
badge.](images/module-4-agents-list.png)

Screenshots in this workshop were captured with the suffix `demo`; yours
carry whatever you chose.

## 4. Try it

Open the agent and use the playground:

![The agent's Playground tab showing Model asg-chat, the composed Instructions
beginning "# Support Explainer Agent", empty Tools and Knowledge sections, and
a chat pane on the right.](images/module-4-agent-detail.png)

Note the **Knowledge** section is empty. That matters in a moment.

> What does the dealer group say about enquiry response when first reply
> times are slower than the standard?

Then try something the attached knowledge cannot answer:

> What is the dealer group's policy on staff parking permits?

It answers from the model's own prior knowledge instead of saying "I don't
know". The `grounding_rules` in the frontmatter say to prefer attached
knowledge, and **there is no attached knowledge yet** — so "prefer" has
nothing to prefer, and the model falls back on what it absorbed in training.

Keep that answer. Module 6 attaches a real knowledge source and you will ask
the same question again.

## 5. Now make it reproducible

What you just did by hand does not survive a new project, a new person, or a
code review. The definition in `agents/support-explainer/` does.

Dry run first — this prints what it would do and calls nothing:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_prompt_agents.py --workshop-only --suffix <your-alias>
```

Then publish:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_prompt_agents.py --workshop-only --suffix <your-alias> --apply
```

Because you used the same name, this does not create a second agent — it adds
a **version** to the one you made. Expect a new version even though you pasted
the same text: the publisher also applies `temperature: 0.2` from
`manifest.yaml`, which the portal did not. If you get no new version, the two
definitions were already identical, which is the same answer from the other
direction.

To compare them properly, put the portal's Instructions box beside the output
of `--show-instructions`. The `instructions_hash` is the tooling's version of
that comparison, and it is printed by `validate_agent_definitions.py` — the
portal never shows it.

`--suffix` is required, not optional. Module 8 needs a published `-baseline`
variant addressable alongside the `-strict` agent you build by hand, and the
cleanup in Module 10 matches on the suffix, so it removes exactly what you
published.

`--workshop-only` limits this to the standalone agent. Module 3 publishes the
three coordinator roles with `--roles-only`, which deliberately leaves this
agent alone — once you attach a knowledge base to it in Module 6, a bare
`--apply` would replace it with a version that has none.

## 6. Version it

Edit one line of `agent.md` — tighten the six-sentence limit to three. Re-run
validate (watch the hash change), then re-publish with `--apply`.

In the portal, the agent gains another version. Prompt agents are
versioned artifacts, which is what makes "who changed the prompt and when"
answerable.

![The agent's version selector expanded, showing Version 2 selected and
Version 1 beneath it, along with Compare versions and Show all version
history.](images/module-4-agent-versions.png)

That capture is the state after section 5; once your edit here publishes you
will have one more version than it shows. The count matters less than the
fact that each publish is a separate, comparable artifact.

Republishing without editing anything does **not** create a version. The
publisher is idempotent on identical content, so if you expected a new
version and did not get one, check that your edit actually reached the
composed instructions — the `instructions_hash` is the thing to compare.

You can also edit instructions directly in the portal. Do that and the two
diverge: the next `--apply` overwrites your portal edit with what is on disk,
silently. Pick one source of truth. For the rest of this workshop it is disk.

---

## 7. Optional — publish from a pipeline

**Skip this if you are not doing CI.** Nothing later depends on it.

Note what is *not* optional: step 5 itself. Modules 3 and 8 both use the
publisher, so the definition-as-code idea has to land here. What is optional
is moving it off your machine.

The argument for doing so is the one you can now see in the portal. An agent
edited in a browser has no diff, no review, and no answer to "who changed the
prompt before quality dropped". An agent published from `agents/` has all
three, and `instructions_hash` makes "is deployed the same as main?" a
question with a yes-or-no answer.

What makes it awkward is that publishing is not idempotent in the way most
deploys are — it creates a **version** every time the composed instructions
change. Publishing on every push to a shared project gets you a version
history of every work-in-progress commit. Two ways out:

- Publish on tags or on merges to `main`, not on every push.
- Or publish per-developer with `--suffix`, which is exactly what this
  workshop does, and keep the shared name for releases.

The credential story is the same as
[Module 1's optional CI section](module-1-deploy-the-app.md) — federated, no
stored secret — but the role is different: publishing an agent is a
data-plane call against the project, so the service principal needs
`Cognitive Services User` on the AI Services account, not just Contributor on
the resource group. Module 9's optional section hits the same wall for the
same reason.

---

## Check yourself

- [ ] You created the agent yourself in the portal, not with a script.
- [ ] Your agent appears in the Foundry portal Agents list, with your suffix.
- [ ] You ran it in the playground and got an answer.
- [ ] You found a question it answers confidently and wrongly.
- [ ] You published a second version and can see both.

Next: [Module 5 — Hosted agents](module-5-hosted-agents.md)
