using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace AgenticSupportGuide.Api.Tests;

public sealed class EndpointsTests
{
    [Fact]
    public async Task Health_reports_provider_status()
    {
        using var client = Conftest.MakeDefaultClient();
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/health", TestContext.Current.CancellationToken))!;
        Assert.Equal("agentic-support-guide-api", body["service"]!.GetValue<string>());
        Assert.Equal("entra", body["foundry_auth_mode"]!.GetValue<string>());
        Assert.True(body["provider_configured"]!.GetValue<bool>());
    }

    [Fact]
    public async Task Dashboard_summary_shape()
    {
        using var client = Conftest.MakeDefaultClient();
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/dashboard/summary", TestContext.Current.CancellationToken))!;
        Assert.Equal(4, body["kpi_cards"]!.AsArray().Count);
    }

    [Fact]
    public async Task Scores_summary_shape()
    {
        using var client = Conftest.MakeDefaultClient();
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/scores/summary", TestContext.Current.CancellationToken))!;
        Assert.StartsWith("Generated from local rules", body["generated_by"]!.GetValue<string>(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Operations_and_dealerships()
    {
        using var client = Conftest.MakeDefaultClient();
        var behavior = (await client.Client.GetFromJsonAsync<JsonNode>("/api/operations/summary", TestContext.Current.CancellationToken))!;
        Assert.Equal(Config.Counts.Dealerships * Config.Counts.ScorePeriods, behavior["total_records"]!.GetValue<int>());
        var dealerships = (await client.Client.GetFromJsonAsync<JsonNode>("/api/dealerships", TestContext.Current.CancellationToken))!;
        Assert.Equal(120, dealerships["total"]!.GetValue<int>());
    }

    [Fact]
    public async Task Supports_options()
    {
        using var client = Conftest.MakeDefaultClient();
        var body = (await client.Client.GetFromJsonAsync<JsonNode>("/api/supports/options", TestContext.Current.CancellationToken))!;
        Assert.Equal(120, body["dealerships"]!.AsArray().Count);
    }

    [Fact]
    public async Task Openapi()
    {
        using var client = Conftest.MakeDefaultClient();
        var schema = (await client.Client.GetFromJsonAsync<JsonNode>("/api/openapi.json", TestContext.Current.CancellationToken))!;
        Assert.Equal("Agentic Support Guide API", schema["info"]!["title"]!.GetValue<string>());
    }

    [Fact]
    public async Task Recommendation_envelope_carries_correlation_and_dealer_group()
    {
        var ct = TestContext.Current.CancellationToken;
        using var client = Conftest.MakeDefaultClient();
        var beforeAudit = (await client.Client.GetFromJsonAsync<JsonNode>("/api/audit/events", ct))!["total"]!.GetValue<int>();

        using var resp = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        var body = (await resp.Content.ReadFromJsonAsync<JsonNode>(ct))!;
        Assert.Equal("ok", body["status"]!.GetValue<string>());
        Assert.Equal("GROUP-DEMO", body["dealer_group_id"]!.GetValue<string>());
        Assert.False(string.IsNullOrEmpty(body["correlation_id"]?.GetValue<string>()));
        Assert.NotNull(body["recommendation"]);
        Assert.Equal("GROUP-DEMO", body["recommendation"]!["dealer_group_id"]!.GetValue<string>());
        Assert.Equal("pending_review", body["recommendation"]!["human_review_state"]!.GetValue<string>());
        Assert.NotEmpty(body["recommendation"]!["citations"]!.AsArray());
        foreach (var c in body["recommendation"]!["citations"]!.AsArray())
        {
            Assert.Equal("GROUP-DEMO", c!["dealer_group_id"]!.GetValue<string>());
        }
        Assert.Equal(4, body["agent_trace"]!.AsArray().Count);

        var afterAudit = (await client.Client.GetFromJsonAsync<JsonNode>("/api/audit/events", ct))!["total"]!.GetValue<int>();
        Assert.Equal(beforeAudit + 1, afterAudit);

        // Verify the runtime audit row carries the safe metadata fields.
        var events = (await client.Client.GetFromJsonAsync<JsonNode>("/api/audit/events", ct))!["events"]!.AsArray();
        var last = events[^1]!;
        Assert.Equal(body["correlation_id"]!.GetValue<string>(), last["correlation_id"]!.GetValue<string>());
        Assert.Equal("GROUP-DEMO", last["dealer_group_id"]!.GetValue<string>());
        Assert.True(last["evidence_count"]!.GetValue<int>() >= 1);
        Assert.True(last["citation_count"]!.GetValue<int>() >= 1);
        Assert.False(string.IsNullOrEmpty(last["validator_status"]?.GetValue<string>()));

        // The receipt numbers and the audit row are two producers of one truth.
        Assert.Equal(last["evidence_count"]!.GetValue<int>(), body["evidence_count"]!.GetValue<int>());
        Assert.Equal(last["citation_count"]!.GetValue<int>(), body["citation_count"]!.GetValue<int>());
        Assert.Equal(last["validator_status"]!.GetValue<string>(), body["validator_status"]!.GetValue<string>());
        Assert.True(body["validation_reached"]!.GetValue<bool>());
        Assert.True(body["deterministic_checks_total"]!.GetValue<int>() >= 1);
        Assert.True(body["attempts"]!.GetValue<int>() >= 1);
        Assert.True(body["citations_accepted"]!.GetValue<int>() <= body["citations_proposed"]!.GetValue<int>());
        Assert.Empty(body["unknown_resource_ids"]!.AsArray());
    }

    [Fact]
    public async Task Save_plan_persists_dealer_group_and_review_state()
    {
        var ct = TestContext.Current.CancellationToken;
        using var client = Conftest.MakeDefaultClient();
        using var recResponse = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        var rec = (await recResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!["recommendation"]!.DeepClone();

        using var savedResponse = await client.Client.PostAsJsonAsync(
            "/api/supports/plans",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["selected_goal"] = "GOAL-lead-response-1",
                ["selected_strategies"] = new JsonArray("ST-lead-response-1"),
                ["recommendation"] = rec,
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        var saved = (await savedResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!;
        Assert.Equal("GROUP-DEMO", saved["dealer_group_id"]!.GetValue<string>());
        Assert.Equal("pending_review", saved["human_review_state"]!.GetValue<string>());
    }

    /// <summary>The save endpoint does not re-run the pipeline, so it must re-check.</summary>
    [Fact]
    public async Task Save_plan_rejects_recommendation_from_another_dealer_group()
    {
        var ct = TestContext.Current.CancellationToken;
        using var client = Conftest.MakeDefaultClient();
        using var recResponse = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        var rec = (await recResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!["recommendation"]!.DeepClone();

        using var resp = await client.Client.PostAsJsonAsync(
            "/api/supports/plans",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["selected_goal"] = null,
                ["selected_strategies"] = new JsonArray(),
                ["recommendation"] = rec,
                ["dealer_group_id"] = "GROUP-A",
            },
            ct);
        Assert.Equal(422, (int)resp.StatusCode);
    }

    [Fact]
    public async Task Save_plan_rejects_oversized_rationale()
    {
        var ct = TestContext.Current.CancellationToken;
        using var client = Conftest.MakeDefaultClient();
        using var recResponse = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        var rec = (await recResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!["recommendation"]!.DeepClone();
        rec["rationale"] = new string('x', 5000);

        using var resp = await client.Client.PostAsJsonAsync(
            "/api/supports/plans",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["selected_goal"] = null,
                ["selected_strategies"] = new JsonArray(),
                ["recommendation"] = rec,
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        Assert.Equal(422, (int)resp.StatusCode);
    }

    [Fact]
    public async Task Unknown_dealership_returns_404()
    {
        using var client = Conftest.MakeDefaultClient();
        using var resp = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "DLR-9999",
                ["category"] = "lead-response",
                ["concern_text"] = "test",
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            TestContext.Current.CancellationToken);
        Assert.Equal(404, (int)resp.StatusCode);
    }

    [Fact]
    public async Task Missing_dealer_group_id_rejected_with_422()
    {
        using var client = Conftest.MakeDefaultClient();
        using var resp = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "test",
            },
            TestContext.Current.CancellationToken);
        Assert.Equal(422, (int)resp.StatusCode);
    }
}
