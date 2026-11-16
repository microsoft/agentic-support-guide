# ADR 0007 — Two tracks, Python and .NET, on Microsoft Agent Framework

Status: Accepted
Date: 2026-11-10

## Context

The application and its workshop were built in Python. Teams that build on
.NET asked for the same workshop in C#. A second implementation invites drift:
different behaviour, different documentation, different lessons. The Python
app also carried hand-written plumbing — a step runner, a wall-clock run
budget, a JSON Schema registry, an offline scorer — that would have had to be
written twice.

## Decision

1. **Two complete tracks.** `python/` and `dotnet/` each hold an API, scripts,
   a hosted agent and a Terraform root, and `workshop/python/` and
   `workshop/dotnet/` each hold modules 0-10 and samples 1-7. A learner needs
   only their own track's runtime: the Python track never loads .NET, and the
   .NET track never needs Python.
2. **One copy of everything else.** `agents/`, `evals/`, `apps/web/` (one UI
   that calls either API), `docs/`, `workshop/images/` and `maintenance/` are
   shared.
3. **Agent Framework only.** Anything Microsoft Agent Framework provides is
   used from it in both tracks. Hand-written agent plumbing was removed rather
   than ported, and a capability one language's framework lacks is removed
   from both.
4. **Conformance goldens pin the behaviour.** `conformance/` records what the
   Python app does — responses, errors, outgoing model requests, workflow
   runs — and the .NET tests replay it. Differences that come from the two
   frameworks themselves are listed in
   [`conformance/allowed_differences.yaml`](../../conformance/allowed_differences.yaml);
   any other difference is a bug.
5. **Separate pipelines.** Each track has its own CI, deploy and evaluation
   workflows, and its own GitHub environment (`workshop`,
   `workshop-dotnet`), so both run from one repository without sharing
   settings.

## Consequences

**Good**

- The same lessons, outputs and failure modes in both languages.
- Drift between the tracks fails a test instead of reaching a learner.
- A learner picks a language without losing any content.

**Costs**

- Every behaviour change lands twice, and an intended Python change means
  regenerating the goldens.
- Framework differences have to be found, explained and recorded.
- Two live environments to keep deployed and verified.

## Alternatives rejected

- **A repository per language.** Shared assets would be copied, and drift
  between the copies would go unnoticed.
- **A .NET appendix to the Python workshop.** Not a real .NET experience.
- **Porting the hand-written plumbing to .NET.** It would double exactly the
  code that Agent Framework makes unnecessary.
