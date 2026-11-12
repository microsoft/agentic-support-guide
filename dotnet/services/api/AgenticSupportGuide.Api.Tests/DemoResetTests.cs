using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace AgenticSupportGuide.Api.Tests;

public sealed class DemoResetTests
{
    [Fact]
    public async Task Demo_reset_returns_403_when_flag_disabled()
    {
        using var client = Conftest.MakeDefaultClient();
        using var resp = await client.Client.PostAsync("/api/demo/reset", null, TestContext.Current.CancellationToken);
        Assert.Equal(403, (int)resp.StatusCode);
    }

    [Fact]
    public async Task Demo_reset_clears_runtime_state_when_enabled()
    {
        var ct = TestContext.Current.CancellationToken;
        using var client = Conftest.MakeDefaultClient(demoResetEnabled: true);

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
        var rec = (await recResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!;
        using var savedResponse = await client.Client.PostAsJsonAsync(
            "/api/supports/plans",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["selected_goal"] = "GOAL-lead-response-1",
                ["selected_strategies"] = new JsonArray("ST-lead-response-1"),
                ["recommendation"] = rec["recommendation"]!.DeepClone(),
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);

        var plansBefore = (await client.Client.GetFromJsonAsync<JsonNode>("/api/supports/plans", ct))!["total"]!.GetValue<int>();
        var auditBefore = (await client.Client.GetFromJsonAsync<JsonNode>("/api/audit/events", ct))!["total"]!.GetValue<int>();
        Assert.True(plansBefore > 10);
        Assert.True(auditBefore > 60);

        using var resp = await client.Client.PostAsync("/api/demo/reset", null, ct);
        Assert.Equal(200, (int)resp.StatusCode);
        var body = (await resp.Content.ReadFromJsonAsync<JsonNode>(ct))!;
        Assert.Equal("ok", body["status"]!.GetValue<string>());

        var afterPlans = (await client.Client.GetFromJsonAsync<JsonNode>("/api/supports/plans", ct))!["total"]!.GetValue<int>();
        var afterAudit = (await client.Client.GetFromJsonAsync<JsonNode>("/api/audit/events", ct))!["total"]!.GetValue<int>();
        Assert.Equal(10, afterPlans);
        Assert.Equal(60, afterAudit);
    }
}
