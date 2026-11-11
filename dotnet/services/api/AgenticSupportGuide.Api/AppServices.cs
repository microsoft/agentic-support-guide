using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;

namespace AgenticSupportGuide.Api;

/// <summary>
/// The objects the app builds once at startup and every request reads.
/// </summary>
/// <remarks>Not immutable: tests swap <c>Settings</c> and <c>Runtime</c> on an app they have already built.</remarks>
public sealed class AppServices
{
    public required AzureFoundrySettings Settings { get; set; }

    public required Repositories Repos { get; init; }

    public required SavedPlansStore PlansStore { get; init; }

    public required RuntimeAuditLog RuntimeAudit { get; init; }

    public required IEvidenceRetriever EvidenceRetriever { get; set; }

    public MafAgentRuntime? Runtime { get; set; }
}

/// <summary>
/// What a test can substitute when it builds the app: the parts that would
/// otherwise reach Azure.
/// </summary>
public sealed record AppOverrides(
    MafAgentRuntime? Runtime = null,
    Func<string, RoleClientFactory>? ClientFactory = null,
    IEvidenceRetriever? EvidenceRetriever = null);

/// <summary>Builds the <see cref="AppServices"/> graph from the environment.</summary>
public static class AppServicesFactory
{
    public static AppServices Build(AppOverrides? overrides, ILoggerFactory loggerFactory)
    {
        var settings = AzureFoundrySettings.Load();

        // Agent Framework emits every workflow, executor and model span from here on.
        Observability.Configure(settings.ApplicationInsightsConnectionString);

        var repos = Repositories.Build();
        var plansStore = new SavedPlansStore();
        plansStore.Seed(repos.SeededPlans, repos.Dealerships);

        return new AppServices
        {
            Settings = settings,
            Repos = repos,
            PlansStore = plansStore,
            RuntimeAudit = new RuntimeAuditLog(),
            EvidenceRetriever = overrides?.EvidenceRetriever ?? BuildEvidenceRetriever(),
            Runtime = overrides?.Runtime ?? BuildRuntime(settings, overrides?.ClientFactory, loggerFactory),
        };
    }

    /// <summary>
    /// Fixtures or Foundry IQ, chosen by EVIDENCE_SOURCE.
    /// </summary>
    /// <remarks>
    /// Fixtures are the default so tests and CI stay offline and free. Setting
    /// EVIDENCE_SOURCE=foundry_iq is what makes the app serve real retrieved
    /// evidence instead of in-memory data.
    /// </remarks>
    private static IEvidenceRetriever BuildEvidenceRetriever()
    {
        var source = (Environment.GetEnvironmentVariable("EVIDENCE_SOURCE") ?? "fixtures").Trim().ToLowerInvariant();
        return source switch
        {
            "" or "fixtures" => new FixtureEvidenceRetriever(),
            "foundry_iq" => new FoundryIqEvidenceRetriever(
                endpoint: Environment.GetEnvironmentVariable("AZURE_SEARCH_ENDPOINT") ?? "",
                knowledgeBase: Environment.GetEnvironmentVariable("FOUNDRY_IQ_KNOWLEDGE_BASE") ?? "",
                knowledgeSource: Environment.GetEnvironmentVariable("FOUNDRY_IQ_KNOWLEDGE_SOURCE") ?? ""),
            _ => throw new InvalidOperationException($"Unknown EVIDENCE_SOURCE '{source}'. Use 'fixtures' or 'foundry_iq'."),
        };
    }

    /// <summary>
    /// Assemble role definitions from agent.md + per-role model deployments.
    /// </summary>
    /// <remarks>
    /// There are no persisted agents to look up: a role is available when its
    /// definition loads and its model deployment variable is set.
    /// </remarks>
    private static MafAgentRuntime? BuildRuntime(AzureFoundrySettings settings, Func<string, RoleClientFactory>? clientFactory, ILoggerFactory loggerFactory)
    {
        if (string.IsNullOrEmpty(settings.ProjectEndpoint))
        {
            return null;
        }
        var roles = RoleDefinitions.LoadRoleDefinitions();
        if (roles.Count == 0)
        {
            return null;
        }
        var factory = clientFactory is not null
            ? clientFactory(settings.ProjectEndpoint)
            : new FoundryResponsesClientFactory(settings.ProjectEndpoint, loggerFactory: loggerFactory).InvokeAsync;
        return new MafAgentRuntime(roles, factory);
    }
}
