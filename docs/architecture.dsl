workspace "Agentic Support Guide" "High-level C4 container view for the demo." {

    model {
        demoUser = person "Demo User"

        asg = softwareSystem "Agentic Support Guide" {
            webApp = container "Web App" "React and TypeScript user interface" {
                tags "LocalApp"
            }
            apiService = container "API Service" "Hosts deterministic orchestration logic that calls remote agents" {
                tags "LocalApp"
            }
            syntheticData = container "Synthetic Data" "In-memory synthetic learner signals" {
                tags "Data"
            }
            agentDefinitions = container "Agent Definitions" "Source-controlled agent.md and manifest.yaml files" {
                tags "AgentAssets"
            }
            protocolContracts = container "Protocol Contracts" "Versioned JSON Schema message contracts" {
                tags "AgentAssets"
            }
        }

        foundry = softwareSystem "Azure AI Foundry" {
            foundryProject = container "Foundry Project" "Azure AI Foundry project boundary" {
                tags "Azure"
            }
            remoteAgents = container "Remote Foundry Agents" "Data Analyst Agent, Support Recommendation Agent, Validator Agent" {
                tags "Azure"
            }
            modelDeployment = container "Model Deployment" "Azure-hosted model used by remote agents" {
                tags "Azure"
            }
            observability = container "Observability" "Metadata-only telemetry and audit events" {
                tags "Azure"
            }
        }

        operations = softwareSystem "Operations" {
            terraformAndScripts = container "Terraform and Scripts" "Provision resources, sync agents, and verify demo readiness" {
                tags "Ops"
            }
        }

        demoUser -> webApp "uses"
        webApp -> apiService "HTTP /api"
        apiService -> syntheticData "reads synthetic data"
        apiService -> protocolContracts "validates messages"
        apiService -> agentDefinitions "loads sync metadata"
        terraformAndScripts -> agentDefinitions "syncs definitions"
        terraformAndScripts -> foundry "provisions and verifies"
        apiService -> remoteAgents "invokes via Foundry Agents SDK"
        apiService -> foundry "keyless Entra ID"
        remoteAgents -> modelDeployment "uses model"
        remoteAgents -> foundryProject "hosted in project"
        apiService -> observability "emits metadata only"
    }

    views {
        container asg "AgenticSupportGuideContainers" "Container view for Agentic Support Guide." {
            include *
            autoLayout lr
        }

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
        }
    }
}
