using AgenticSupportGuide.Api.FoundryAgents;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Builds the real app for a test, with the environment it would read and the
/// parts that would reach Azure substituted.
/// </summary>
public sealed class TestApp : IDisposable
{
    public const string TestApiKey = "test-shared-key-not-a-real-secret";

    // Every environment variable the app reads. Each app starts from none of
    // them set, then applies its own configuration.
    public static readonly string[] AppEnv =
    [
        "API_SHARED_KEY",
        "WEBSITE_SITE_NAME",
        "BUILD_ID",
        "EVIDENCE_SOURCE",
        "ALLOWED_ORIGINS",
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AUTH_MODE",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "DEMO_RESET_ENABLED",
        "FOUNDRY_MODEL_DEPLOYMENT_ANALYST",
        "FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER",
        "FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR",
        "FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER",
    ];

    private static readonly string[] RoleDeploymentEnv =
    [
        "FOUNDRY_MODEL_DEPLOYMENT_ANALYST",
        "FOUNDRY_MODEL_DEPLOYMENT_RECOMMENDER",
        "FOUNDRY_MODEL_DEPLOYMENT_VALIDATOR",
    ];

    private readonly Dictionary<string, string?> _saved;
    private readonly WebApplicationFactory<Program> _factory;

    private TestApp(Dictionary<string, string?> saved, WebApplicationFactory<Program> factory, HttpClient client)
    {
        _saved = saved;
        _factory = factory;
        Client = client;
    }

    public HttpClient Client { get; }

    public AppServices Services => _factory.Services.GetRequiredService<AppServices>();

    /// <summary>
    /// Start the app with <paramref name="environment"/> applied over a clean
    /// slate. The three role deployments are always set, as the Python tests'
    /// autouse fixture sets them. The runtime is built after the environment is
    /// applied, because role definitions read it.
    /// </summary>
    public static TestApp Start(
        IReadOnlyDictionary<string, string>? environment = null,
        Func<MafAgentRuntime?>? runtime = null,
        Evidence.IEvidenceRetriever? evidenceRetriever = null)
    {
        var saved = AppEnv.ToDictionary(name => name, Environment.GetEnvironmentVariable);
        foreach (var name in AppEnv)
        {
            Environment.SetEnvironmentVariable(name, null);
        }
        foreach (var name in RoleDeploymentEnv)
        {
            Environment.SetEnvironmentVariable(name, FakeChatClientFactory.DefaultDeployment);
        }
        foreach (var (name, value) in environment ?? new Dictionary<string, string>())
        {
            Environment.SetEnvironmentVariable(name, value);
        }

        var overrides = new AppOverrides(Runtime: runtime?.Invoke(), EvidenceRetriever: evidenceRetriever);
        var factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            builder.UseEnvironment("Production");
            builder.ConfigureServices(services => services.AddSingleton(overrides));
        });
        var client = factory.CreateClient(new WebApplicationFactoryClientOptions
        {
            BaseAddress = new Uri("http://testserver"),
            AllowAutoRedirect = false,
        });
        return new TestApp(saved, factory, client);
    }

    public void Dispose()
    {
        Client.Dispose();
        _factory.Dispose();
        foreach (var (name, value) in _saved)
        {
            Environment.SetEnvironmentVariable(name, value);
        }
    }
}
