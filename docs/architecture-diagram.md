# High-level component architecture

Option 1 runtime: a deterministic FastAPI coordinator dispatches to three
remote Azure AI Foundry Agent Service agents. The coordinator is
service-side orchestration — it is not a fourth agent and never calls a
base model directly. All data in the demo is synthetic; no prompts or
completions are logged.

```mermaid
flowchart LR
    subgraph DevCI["Developer Workstation / CI"]
        TF["/infra Terraform"]
        SYNC["/scripts/sync_foundry_agents.py"]
        VERIFY["/scripts/verify-demo.ps1"]
        AGENTS["/agents (agent.md + manifest.yaml)"]
        CONTRACTS["/contracts/v1 (JSON Schemas)"]
        EVALS["/evals (synthetic cases)"]
    end

    subgraph LocalApp["Local Application"]
        USER["Browser / demo user"]
        WEB["/apps/web (React + TS)"]
        API["/services/api (FastAPI)"]
        COORD["Remote-agent Coordinator (deterministic)"]
        HEALTH["/api/health/details"]
        AUDIT["/api/audit (metadata only)"]
        REPOS["Synthetic in-memory repositories"]
    end

    subgraph Foundry["Azure AI Foundry"]
        PROJ["Foundry Project"]
        A1["Data Analyst Agent"]
        A2["Support Recommendation Agent"]
        A3["Validator Agent"]
        MODEL["Foundry model deployment"]
        AI["Application Insights / Azure Monitor"]
        LAW["Log Analytics"]
    end

    subgraph Gov["Governance / GenAIOps"]
        GAGENTS["Agent instruction / version governance"]
        GCONTRACTS["Protocol governance"]
        GEVALS["Synthetic eval cases"]
        GOBS["Metadata-only observability"]
        GHUMAN["Human review + RAI caveats"]
    end

    USER -- "HTTP /api" --> WEB
    WEB -- "HTTP /api" --> API
    API --> COORD
    API --> HEALTH
    API --> AUDIT
    API --> REPOS

    COORD -- "validates schema" --> CONTRACTS
    COORD -- "invokes remote agent" --> A1
    COORD -- "invokes remote agent" --> A2
    COORD -- "invokes remote agent" --> A3
    COORD -- "keyless Entra ID" --> PROJ

    A1 --> MODEL
    A2 --> MODEL
    A3 --> MODEL
    A1 -- "response" --> COORD
    A2 -- "response" --> COORD
    A3 -- "response" --> COORD

    COORD -- "recommendation + safe trace" --> API
    API -- "safe response" --> WEB
    AUDIT -- "emits metadata" --> AI
    AI --> LAW

    TF -- "provisions" --> PROJ
    TF -- "provisions" --> MODEL
    TF -- "provisions" --> AI
    SYNC -- "syncs definitions" --> A1
    SYNC -- "syncs definitions" --> A2
    SYNC -- "syncs definitions" --> A3
    SYNC --> AGENTS
    VERIFY -- "checks demo readiness" --> HEALTH

    AGENTS --> GAGENTS
    CONTRACTS --> GCONTRACTS
    EVALS --> GEVALS
    AI --> GOBS
    COORD --> GHUMAN
```

## Notes

- GitHub and VS Code both preview Mermaid natively; open this file to
  see the diagram.
- To edit in draw.io / diagrams.net, use Arrange -> Insert -> Advanced ->
  Mermaid and paste the block above.
- The coordinator is deterministic Python. All reasoning happens in the
  three remote Foundry agents.
- No prompts or completions are logged. Audit rows and Application
  Insights carry metadata only.
- Data used by the demo is entirely synthetic.
