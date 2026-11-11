using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;

namespace AgenticSupportGuide.Api;

/// <summary>
/// What is actually configured, decided without any network calls.
/// </summary>
/// <remarks>
/// The frontend polls /api/health/details on every page load, so every field
/// here has to be answerable locally.
/// </remarks>
public sealed record SetupState(
    bool ProjectConfigured,
    bool DeploymentsConfigured,
    IReadOnlyList<string> MissingDeployments,
    bool DefinitionsValid,
    bool EvidenceAvailable,
    bool EvidenceVerified,
    string EvidenceSource,
    string EvidenceKnowledgeBase,
    string AuthMode,
    bool ApplicationInsightsConfigured)
{
    public static SetupState Inspect(AzureFoundrySettings settings, MafAgentRuntime? runtime, IEvidenceRetriever? evidenceRetriever)
    {
        var missing = RoleDefinitions.MissingModelDeployments();
        var available = evidenceRetriever is not null && DealerGroups.KnownDealerGroups.Any(evidenceRetriever.HasDealerGroup);
        return new SetupState(
            ProjectConfigured: settings.Configured,
            DeploymentsConfigured: missing.Count == 0,
            MissingDeployments: missing,
            // There are no persisted agents to bind to: a role is ready when
            // its definition loads and its model deployment variable is set.
            DefinitionsValid: runtime is not null && runtime.AllRolesAvailable(Diagnostics.RequiredRoles),
            EvidenceAvailable: available,
            // A remote retriever cannot confirm evidence exists without a
            // network call, so configuration and verification are reported as
            // two different things instead of being conflated.
            EvidenceVerified: available && (evidenceRetriever?.EvidenceVerifiable ?? true),
            EvidenceSource: evidenceRetriever?.ProviderName ?? "none",
            EvidenceKnowledgeBase: evidenceRetriever?.ProviderModel ?? "",
            AuthMode: settings.AuthMode,
            ApplicationInsightsConfigured: !string.IsNullOrEmpty(settings.ApplicationInsightsConnectionString));
    }

    public string ActiveProvider =>
        ProjectConfigured && DefinitionsValid && DeploymentsConfigured && EvidenceAvailable ? MafAgentRuntime.ProviderId : "unconfigured";
}

/// <summary>
/// Setup diagnostics for the demo-friendly /api/health/details endpoint.
/// </summary>
/// <remarks>
/// Returns human-readable configuration status only. Never includes secrets,
/// endpoint URLs, tokens, connection strings, or raw environment values.
///
/// <see cref="SetupState.Inspect"/> decides what is true; the methods here
/// decide how to say it.
/// </remarks>
public static class Diagnostics
{
    public const string ServiceStatus = "ok";

    public static readonly IReadOnlyList<string> RequiredRoles =
        [DataAnalystAgent.AgentName, SupportRecommendationAgent.AgentName, ValidatorAgent.AgentName];

    // dealer_group_id is required by the contracts themselves, so this is a
    // property of the build rather than of the environment.
    public const bool DealerGroupIsolationEnabled = true;

    public static HealthDetailsResponse BuildHealthDetails(
        AzureFoundrySettings settings,
        MafAgentRuntime? runtime,
        IEvidenceRetriever? evidenceRetriever,
        string service,
        string version)
    {
        var state = SetupState.Inspect(settings, runtime, evidenceRetriever);
        var activeProvider = state.ActiveProvider;
        var remoteWorkflowActive = activeProvider == MafAgentRuntime.ProviderId;

        return new HealthDetailsResponse(
            Status: ServiceStatus,
            Service: service,
            Version: version,
            ActiveProvider: activeProvider,
            FoundryProjectConfigured: state.ProjectConfigured,
            AgentDefinitionsValid: state.DefinitionsValid,
            ModelDeploymentsConfigured: state.DeploymentsConfigured,
            ServiceSideRemoteWorkflowActive: remoteWorkflowActive,
            EvidenceFixtureAvailable: state.EvidenceAvailable,
            EvidenceSource: state.EvidenceSource,
            EvidenceKnowledgeBase: state.EvidenceKnowledgeBase,
            EvidenceVerified: state.EvidenceVerified,
            ApiAuthMode: Auth.ApiAuthMode(),
            DealerGroupIsolationEnabled: DealerGroupIsolationEnabled,
            CustomerDemoReady: remoteWorkflowActive,
            Checks: Checks(state),
            Warnings: Warnings(state),
            Guidance: Guidance(activeProvider));
    }

    private static HealthCheckItem EvidenceCheck(SetupState state)
    {
        string label, detail;
        if (state.EvidenceVerified)
        {
            label = "Synthetic evidence fixture available";
            detail = "At least one group-scoped fixture is present.";
        }
        else if (state.EvidenceAvailable)
        {
            label = "Evidence source configured (not verified)";
            detail = $"Configured against {Parity.PyText.Repr(state.EvidenceSource)}. Presence of evidence is not checked here; run a real request to confirm.";
        }
        else
        {
            label = "Evidence source configured (not verified)";
            detail = "No group-scoped fixtures loaded.";
        }
        return new HealthCheckItem("evidence_fixture", label, state.EvidenceAvailable, detail);
    }

    private static List<HealthCheckItem> Checks(SetupState state)
    {
        var entra = state.AuthMode == "entra";
        return
        [
            new("backend", "Backend service running", true, "The API is responding to requests."),
            new(
                "foundry_project_endpoint",
                "Microsoft Foundry project endpoint configured",
                state.ProjectConfigured,
                state.ProjectConfigured ? "Set. Endpoint value hidden." : "Not set. Populate AZURE_AI_FOUNDRY_PROJECT_ENDPOINT."),
            new(
                "model_deployments_configured",
                "Per-role model deployments configured",
                state.DeploymentsConfigured,
                state.DeploymentsConfigured
                    ? "All three role deployments are set."
                    : $"Missing: {string.Join(", ", state.MissingDeployments)}. Run {Track.PopulateEnv}."),
            new(
                "agent_definitions_valid",
                "Agent definitions loaded",
                state.DefinitionsValid,
                state.DefinitionsValid ? "All three role definitions loaded from /agents." : "One or more agent definitions could not be loaded."),
            EvidenceCheck(state),
            new(
                "dealer_group_isolation",
                "Dealer group isolation enforced by contracts",
                DealerGroupIsolationEnabled,
                "dealer_group_id is required on every request, envelope, citation, audit row, and trace."),
            new(
                "auth_mode",
                "Foundry authentication mode",
                entra,
                entra
                    ? "This API authenticates to Microsoft Foundry with Microsoft Entra ID (no keys). Separate from api_auth_mode, which is how callers authenticate to this API."
                    : "Non-default Foundry auth mode. Only 'entra' is supported by this build."),
            new(
                "application_insights",
                "Application Insights configured",
                state.ApplicationInsightsConfigured,
                state.ApplicationInsightsConfigured ? "Set. Telemetry emits metadata only." : "Not set (optional). Telemetry no-ops."),
        ];
    }

    /// <summary>
    /// Only the first unmet prerequisite in the chain is reported.
    /// </summary>
    /// <remarks>
    /// Reporting unloadable agent definitions is noise when the real problem is
    /// that no project endpoint has been configured yet.
    /// </remarks>
    private static List<string> Warnings(SetupState state)
    {
        var warnings = new List<string>();
        if (!state.ProjectConfigured)
        {
            warnings.Add(
                "Microsoft Foundry project endpoint is not configured. Recommendation "
                + "requests will fail with a typed provider_missing error until "
                + "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is set.");
        }
        else if (!state.DeploymentsConfigured)
        {
            warnings.Add(
                "Foundry project is configured but per-role model deployments are "
                + $"missing. Run {Track.PopulateEnv} to regenerate "
                + $"{Track.EnvFile}, then restart the backend with "
                + $"{Track.RunBackend}.");
        }
        else if (!state.DefinitionsValid)
        {
            warnings.Add(
                "Agent definitions in /agents could not be loaded. Run "
                + $"'{Track.ValidateAgentDefinitionsCommand}' to see why.");
        }
        if (!state.EvidenceAvailable)
        {
            warnings.Add(
                "No group-scoped evidence fixture is loaded. Recommendation requests "
                + "will return evidence_missing until a fixture is registered.");
        }
        return warnings;
    }

    private static string Guidance(string activeProvider)
    {
        if (activeProvider == MafAgentRuntime.ProviderId)
        {
            return "Ready for a live demo. Sign in with 'az login' if you have not already. "
                + "First-request RBAC propagation may take a few minutes; retry if you see 401/403.";
        }
        return $"Not demo-ready. To finish setup: run Terraform in {Track.InfraDir}, run "
            + $"{Track.PopulateEnv} to write {Track.EnvFile}, then start the "
            + $"backend with {Track.RunBackend}. No agent deployment step is needed - "
            + "agent definitions live in /agents and load at runtime.";
    }
}
