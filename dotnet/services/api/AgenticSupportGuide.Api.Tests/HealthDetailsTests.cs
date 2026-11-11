using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace AgenticSupportGuide.Api.Tests;

public sealed class HealthDetailsTests
{
    private static readonly string CanaryEndpoint = "https://sensitive-endpoint-value.example.invalid/api/projects/asg";
    private static readonly string CanaryConnStr = "InstrumentationKey=SENSITIVE_CANARY_KEY;IngestionEndpoint=hidden";

    [Fact]
    public async Task Health_details_reports_ready_with_definitions_and_fixture()
    {
        using var client = Conftest.MakeDefaultClient();
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/health/details", TestContext.Current.CancellationToken))!;
        Assert.Equal("ok", body["status"]!.GetValue<string>());
        Assert.Equal("agentic-support-guide-api", body["service"]!.GetValue<string>());
        Assert.Equal("azure_foundry_responses", body["active_provider"]!.GetValue<string>());
        Assert.True(body["foundry_project_configured"]!.GetValue<bool>());
        Assert.True(body["agent_definitions_valid"]!.GetValue<bool>());
        Assert.True(body["service_side_remote_workflow_active"]!.GetValue<bool>());
        Assert.True(body["evidence_fixture_available"]!.GetValue<bool>());
        Assert.True(body["dealer_group_isolation_enabled"]!.GetValue<bool>());
        Assert.True(body["customer_demo_ready"]!.GetValue<bool>());
        var checks = body["checks"]!.AsArray();
        Assert.Contains(checks, check => check!["name"]!.GetValue<string>() == "backend" && check["ok"]!.GetValue<bool>());
        Assert.Contains(checks, check => check!["name"]!.GetValue<string>() == "foundry_project_endpoint");
        Assert.Contains(checks, check => check!["name"]!.GetValue<string>() == "agent_definitions_valid");
        Assert.Contains(checks, check => check!["name"]!.GetValue<string>() == "evidence_fixture");
        Assert.Contains(checks, check => check!["name"]!.GetValue<string>() == "dealer_group_isolation");
    }

    [Fact]
    public async Task Health_details_unconfigured_when_project_endpoint_missing()
    {
        using var client = Conftest.MakeDefaultClient();
        client.Services.Settings = new AzureFoundrySettings(
            ProjectEndpoint: null,
            AuthMode: "entra",
            ApplicationInsightsConnectionString: null,
            DemoResetEnabled: false);
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/health/details", TestContext.Current.CancellationToken))!;

        Assert.Equal("unconfigured", body["active_provider"]!.GetValue<string>());
        Assert.False(body["foundry_project_configured"]!.GetValue<bool>());
        Assert.False(body["service_side_remote_workflow_active"]!.GetValue<bool>());
        Assert.False(body["customer_demo_ready"]!.GetValue<bool>());
        Assert.NotEmpty(body["warnings"]!.AsArray());
    }

    [Fact]
    public async Task Health_details_unconfigured_when_definitions_missing()
    {
        using var client = Conftest.MakeDefaultClient();
        client.Services.Runtime = null;
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/health/details", TestContext.Current.CancellationToken))!;

        Assert.Equal("unconfigured", body["active_provider"]!.GetValue<string>());
        Assert.False(body["agent_definitions_valid"]!.GetValue<bool>());
        Assert.False(body["service_side_remote_workflow_active"]!.GetValue<bool>());
        Assert.False(body["customer_demo_ready"]!.GetValue<bool>());
    }

    [Fact]
    public async Task Health_details_does_not_expose_secrets()
    {
        using var client = Conftest.MakeDefaultClient();
        var payload = (await client.Client.GetStringAsync("/api/health/details", TestContext.Current.CancellationToken)).ToLowerInvariant();
        foreach (var forbidden in new[] { "connection_string=", "endpoint=", "secret", "key=", "token" })
        {
            Assert.DoesNotContain(forbidden, payload, StringComparison.Ordinal);
        }
    }

    [Fact]
    public async Task Health_details_does_not_leak_any_configured_env_values()
    {
        using var client = Conftest.MakeDefaultClient();
        client.Services.Settings = new AzureFoundrySettings(
            ProjectEndpoint: CanaryEndpoint,
            AuthMode: "entra",
            ApplicationInsightsConnectionString: CanaryConnStr,
            DemoResetEnabled: false);

        var payload = await client.Client.GetStringAsync("/api/health/details", TestContext.Current.CancellationToken);
        foreach (var canary in new[] { CanaryEndpoint, CanaryConnStr })
        {
            Assert.DoesNotContain(canary, payload, StringComparison.Ordinal);
        }
    }
}
