workspace "Agentic Support Guide" "High-level C4 container and component views for the demo." {

    model {
        demoUser = person "Demo User"

        asg = softwareSystem "Agentic Support Guide" {
            webApp = container "Web App" "React and TypeScript user interface" {
                tags "LocalApp"
            }
            apiService = container "API Service" "FastAPI backend that owns request handling and error taxonomy" {
                tags "LocalApp"
                coordinator = component "Workflow Coordinator" "Deterministic Python that sequences the three remote agents, validates protocol messages, and runs a one-shot repair loop"
            }
            syntheticData = container "Synthetic Data" "In-memory synthetic learner signals" {
                tags "Data"
            }
            evidenceRetriever = container "Evidence Retriever" "EvidenceRetriever interface; synthetic fixtures per district today; Fabric-backed in production" {
                tags "Data"
            }
            humanReview = container "Human Review" "Review lifecycle (pending, approved, rejected) with audited transitions" {
                tags "LocalApp"
            }
            agentDefinitions = container "Agent Definitions" "Source-controlled agent.md and manifest.yaml files" {
                tags "AgentAssets"
            }
            protocolContracts = container "Protocol Contracts" "Versioned JSON Schema message contracts including district_id and citations" {
                tags "AgentAssets"
            }
        }

        fabric = softwareSystem "Microsoft Fabric (per district)" "Target production data tier. Each district has its own workspace and lakehouse. Not wired up in this build." {
            fabricDistA = container "District A workspace + lakehouse" "Structured tables and district-approved PDFs for District A" {
                tags "Fabric"
            }
            fabricDistB = container "District B workspace + lakehouse" "Structured tables and district-approved PDFs for District B" {
                tags "Fabric"
            }
        }

        foundry = softwareSystem "Azure AI Foundry" {
            foundryProject = container "Foundry Project" "Project boundary for agents, model, and observability" {
                tags "Azure"
            }
            remoteAgents = container "Remote Foundry Agents" "Hosts the three role agents in Azure AI Foundry Agent Service" {
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
            terraformAndScripts = container "Terraform & Sync Scripts" "Provision Azure resources, sync agents, and verify demo readiness" {
                tags "Ops"
            }
        }

        # Relationships
        demoUser -> webApp "uses"
        webApp -> apiService "HTTP /api"

        coordinator -> syntheticData "reads"
        coordinator -> evidenceRetriever "retrieves per-district evidence bundle"
        coordinator -> protocolContracts "validates"
        coordinator -> agentDefinitions "loads"
        coordinator -> dataAnalystAgent "invokes via Foundry Agents SDK"

        dataAnalystAgent -> supportRecommendationAgent "passes evidence"
        supportRecommendationAgent -> validatorAgent "passes draft"

        coordinator -> humanReview "creates draft in pending_review"
        webApp -> humanReview "approves or rejects"

        evidenceRetriever -> fabricDistA "district-scoped read (target production)"
        evidenceRetriever -> fabricDistB "district-scoped read (target production)"

        remoteAgents -> modelDeployment "uses shared model deployment"

        apiService -> observability "emits correlation_id, district_id, coded status only"

        terraformAndScripts -> foundry "provisions and verifies"
        terraformAndScripts -> agentDefinitions "syncs definitions"
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

        component remoteAgents "RemoteFoundryAgentsComponents" "Components inside the Remote Foundry Agents container." {
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
            element "Fabric" {
                background "#3f6b5b"
                color "#ffffff"
            }
        }
    }
}
