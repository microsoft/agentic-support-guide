workspace "Agentic Support Guide" "High-level C4 container and component views for the demo." {

    model {
        demoUser = person "Demo User"

        asg = softwareSystem "Agentic Support Guide" {
            webApp = container "Web App" "React and TypeScript user interface" {
                tags "LocalApp"
            }
            apiService = container "API Service" "FastAPI backend that owns request handling and error taxonomy" {
                tags "LocalApp"
                coordinator = component "Workflow Coordinator" "Deterministic Python that builds the Agent Framework workflow graph, validates every protocol hop, and enforces the run budget"
            }
            syntheticData = container "Synthetic Data" "In-memory synthetic dealership signals" {
                tags "Data"
            }
                tags "Data"
            }
            humanReview = container "Human Review" "Review lifecycle (pending, approved, rejected) with audited transitions" {
                tags "LocalApp"
            }
            agentDefinitions = container "Agent Definitions" "Source-controlled agent.md and manifest.yaml files" {
                tags "AgentAssets"
            }
            protocolContracts = container "Protocol Contracts" "Versioned JSON Schema message contracts including dealer_group_id and citations" {
                tags "AgentAssets"
            }
        }

            }
            }
        }

        foundry = softwareSystem "Microsoft Foundry" {
            foundryProject = container "Foundry Project" "Project boundary for agents, model, and observability" {
                tags "Azure"
            }
            remoteAgents = container "Ephemeral Foundry Agents" "Agent Framework agents assembled in-process per call; the same definitions are also published to Foundry as versioned prompt agents" {
                tags "Azure"
                dataAnalystAgent = component "Data Analyst Agent" "Reviews synthetic signals and writes an evidence summary"
                supportRecommendationAgent = component "Support Recommendation Agent" "Proposes a plan drawn from an allowed catalog"
                validatorAgent = component "Validator Agent" "Checks structure, required caveats, and grounding"
            }
            modelDeployment = container "Model Deployment" "Azure-hosted model used by remote agents" {
                tags "Azure"
            }
            observability = container "Observability" "Metadata-only telemetry and audit events" {
                tags "Azure"
            }
        }

        operations = softwareSystem "Deployment & Operations" {
            terraformAndScripts = container "Terraform & Ops Scripts" "Provision Azure infrastructure, validate agent definitions, and publish agent versions to Foundry." {
                tags "Ops"
            }
        }

        # Relationships
        demoUser -> webApp "uses"
        webApp -> apiService "HTTP /api"

        coordinator -> syntheticData "reads"
        coordinator -> evidenceRetriever "retrieves per-dealer group evidence bundle"
        coordinator -> protocolContracts "validates"
        coordinator -> agentDefinitions "loads"
        coordinator -> dataAnalystAgent "invokes via Microsoft Agent Framework"

        dataAnalystAgent -> supportRecommendationAgent "passes evidence"
        supportRecommendationAgent -> validatorAgent "passes draft"

        coordinator -> humanReview "creates draft in pending_review"
        apiService -> humanReview "approves or rejects (API only; no UI yet)"


        remoteAgents -> modelDeployment "uses shared model deployment"

        apiService -> observability "emits correlation_id, dealer_group_id, coded status only"

        terraformAndScripts -> foundry "provisions and verifies"
        terraformAndScripts -> agentDefinitions "validates definitions (no deploy)"
    }

    views {
        container asg "AgenticSupportGuideContainers" "Container view for Agentic Support Guide." {
            include *
            autoLayout lr
        }

        component apiService "APIServiceComponents" "Components inside the API Service container." {
            include *
            autoLayout lr
        }

        component remoteAgents "EphemeralFoundryAgentsComponents" "Roles composed in-process from /agents definitions." {
            include *
            autoLayout lr
        }

        # C4 element-type labels (e.g. "[Container: ...]", "[Person]") are
        # emitted by Structurizr renderers by default. Suppression varies by
        # export tool and is documented in docs/architecture-diagram.md.
        styles {
            element "Person" {
                shape person
                background "#7f8c8d"
                color "#ffffff"
            }
            element "Software System" {
                background "#95a5a6"
                color "#ffffff"
            }
            element "Container" {
                background "#bdc3c7"
                color "#2c3e50"
            }
            element "Component" {
                background "#dfe4e8"
                color "#2c3e50"
            }
            element "LocalApp" {
                background "#5b8def"
                color "#ffffff"
            }
            element "AgentAssets" {
                background "#9b8ac4"
                color "#ffffff"
            }
            element "Azure" {
                background "#3178c6"
                color "#ffffff"
            }
            element "Ops" {
                background "#6c8ea4"
                color "#ffffff"
            }
            element "Data" {
                background "#8aa27a"
                color "#ffffff"
            }
                background "#3f6b5b"
                color "#ffffff"
            }
        }
    }
}
