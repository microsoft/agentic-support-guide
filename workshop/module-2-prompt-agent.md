# Module 2 — Your first prompt agent

**Time:** about 45 minutes.

**You will have at the end:** an agent you can see, run, and version in the
Foundry portal — built from a file in this repo, with no application code
running anywhere.

---

## The idea

A **prompt agent** is a model deployment plus instructions plus a contract,
stored in Foundry. Foundry runs it. There is no container, no web app, and
nothing of yours to keep alive.

That is the whole thing. If your agent is "answer questions about X using
Y," you do not need to write or host a service. This module is here so you
know where the ceiling is before you start building past it.

Compare the three ways to run an agent on Foundry:

| | Prompt agent | Hosted agent | Direct API call |
| --- | --- | --- | --- |
| Where code runs | Foundry | Foundry-managed container | Your process |
| Visible in portal | Yes | Yes | No |
| Versioned | Yes | Yes | No |
| Own identity | No | Yes, dedicated Entra identity | No |
| Custom dependencies | No | Yes | Yes |
| You operate it | No | No | Yes |

Module 7 builds the hosted variant. Most people need this one.

## 1. Read the agent before you publish it

Open [agents/support-explainer/agent.md](../agents/support-explainer/agent.md).

Two parts matter:

- **YAML frontmatter** — `constraints`, `safety_rules`, `grounding_rules`.
  These are not documentation. They are composed into the instructions the
  model actually receives.
- **Markdown body** — the role description.

This bit me during development and is worth pausing on: an earlier version of
the composer used only the markdown body and silently discarded the
frontmatter. The output stayed *plausible*, so nothing looked broken — it was
just no longer bound by the contract. If you change `agent.md` and behaviour
does not change, check that the part you edited is actually reaching the model
before you start rewriting your prompt.

Now look at [agents/support-explainer/manifest.yaml](../agents/support-explainer/manifest.yaml).
`model_deployment_env` points at an environment variable rather than a
hardcoded deployment name, which is what lets the same definition run against
your deployment and someone else's.

## 2. Validate

```powershell
.\services\api\.venv\Scripts\python.exe scripts\validate_agent_definitions.py
```

This parses the frontmatter, resolves the model deployment, and hashes the
composed instructions. No network calls, so it is fast and safe to run on
every edit.

Note the `instructions_hash` for `support-explainer`. Change one word in
`agent.md`, re-run, and watch it change. That hash is how you tell whether
what you published is what you meant to publish.

## 3. Publish it

Dry run first — this prints what it would do and calls nothing:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_prompt_agents.py --workshop-only --suffix <your-alias>
```

Then publish:

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_prompt_agents.py --workshop-only --suffix <your-alias> --apply
```

`--suffix` is required, not optional. Your agent is published as
`asg-support-explainer-agent-<your-alias>`. The project is yours, so nobody
else is going to overwrite it — the suffix earns its place for two other
reasons. Module 6 publishes two variants of this same definition and needs
them separately addressable, and the cleanup in step 6 matches on the suffix,
so it removes exactly what you published rather than every agent in the
project.

`--workshop-only` limits this to the standalone agent. Drop it later to also
publish the three coordinator roles used in Module 4.

## 4. Look at it in the portal

Open your Foundry project → **Agents**. Your agent is there by name.

Open it and try it in the playground:

> What does the district say about supporting a learner whose letter-sound
> fluency is behind pace?

Then try something the attached knowledge cannot answer:

> What is the district's policy on cafeteria peanut allergies?

Right now it will answer from the model's own prior knowledge instead of
saying "I don't know" — the `grounding_rules` say to prefer attached
knowledge, but **there is no attached knowledge yet**. Instructions alone
cannot make a model refuse to guess. That gap is the entire reason Module 3
exists.

## 5. Version it

Edit one line of `agent.md` — tighten the six-sentence limit to three. Re-run
validate (watch the hash change), then re-publish with `--apply`.

In the portal, the agent now has a second version. Prompt agents are
versioned artifacts, which is what makes "who changed the prompt and when"
answerable.

## 6. Clean up when you are done

```powershell
.\services\api\.venv\Scripts\python.exe scripts\publish_prompt_agents.py --suffix <your-alias> --delete
```

This matches the suffix exactly — not as a prefix — so an agent published
under a different suffix survives. That precision is deliberate: a prefix
match here once deleted more than it was asked to.

---

## Check yourself

- [ ] Your agent appears in the Foundry portal Agents list, with your suffix.
- [ ] You ran it in the playground and got an answer.
- [ ] You found a question it answers confidently and wrongly.
- [ ] You published a second version and can see both.

## What you should be able to explain

- Why a prompt agent needs no hosting.
- Why the instructions hash matters more than the prompt text you remember writing.
- Why `grounding_rules` did not stop the model from guessing.

Next: [Module 3 — Ground it with Foundry IQ](module-3-foundry-iq.md)
