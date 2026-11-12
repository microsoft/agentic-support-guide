namespace AgenticSupportGuide.Api;

/// <summary>
/// Static configuration for the local prototype.
/// </summary>
/// <remarks>
/// Foundry Agent Service settings are read from environment.
/// No secrets are baked in.
/// </remarks>
public static class Config
{
    public const int Seed = 20260101;
    public const string BaseTimestamp = "2026-01-05T09:00:00Z";
    public const string ServiceName = "agentic-support-guide-api";
    public const string ServiceVersion = "0.3.0";

    public const string PrototypeBanner =
        "Prototype - synthetic data, three collaborating agents hosted in " +
        "Foundry Agent Service, not a production system.";

    // What `RecommendationEnvelope.provider_model` reports. The per-step models
    // are in the trace; this names the provider the workflow ran against.
    // apps/web/src/pages/SupportsPage.tsx matches the configured string.
    public const string ProviderDisplayConfigured = "Microsoft Foundry (Agent Framework, prompt agents)";
    public const string ProviderDisplayUnconfigured = "unconfigured (Microsoft Foundry not set up)";

    public const int ConcernTextMaxLen = 1000;

    public const string ContractVersion = "1.0.0";

    public static MockDataCounts Counts { get; } = new();
}

public sealed record MockDataCounts
{
    public int Dealerships { get; init; } = 120;
    // Area scores and operations are complete grids, so their record counts are
    // derived from periods rather than chosen independently.
    public int ScorePeriods { get; init; } = 6;
    public int Resources { get; init; } = 40;
    public int AuditEvents { get; init; } = 60;
    public int SeededPlans { get; init; } = 10;
}

/// <summary>
/// Runtime settings for Foundry Agent Service.
/// </summary>
/// <param name="ProjectEndpoint">The Foundry project endpoint. Required.</param>
/// <param name="AuthMode">Only "entra" (Microsoft Entra ID) is supported.</param>
/// <param name="ApplicationInsightsConnectionString">Optional telemetry sink.</param>
/// <param name="DemoResetEnabled">Dev/demo toggle for /api/demo/reset.</param>
public sealed record AzureFoundrySettings(
    string? ProjectEndpoint,
    string AuthMode,
    string? ApplicationInsightsConnectionString,
    bool DemoResetEnabled)
{
    public bool Configured => !string.IsNullOrEmpty(ProjectEndpoint);

    public static AzureFoundrySettings Load()
    {
        var endpoint = Env("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") ?? Env("AZURE_AI_FOUNDRY_ENDPOINT");
        return new AzureFoundrySettings(
            ProjectEndpoint: endpoint,
            AuthMode: Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_AUTH_MODE") ?? "entra",
            ApplicationInsightsConnectionString: Env("APPLICATIONINSIGHTS_CONNECTION_STRING"),
            DemoResetEnabled: (Environment.GetEnvironmentVariable("DEMO_RESET_ENABLED") ?? "false").Trim().ToLowerInvariant() == "true");
    }

    // An empty variable counts as unset, as `os.environ.get(...) or None` does.
    private static string? Env(string name)
    {
        var value = Environment.GetEnvironmentVariable(name);
        return string.IsNullOrEmpty(value) ? null : value;
    }
}
