using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

public sealed class HumanReviewStateTests
{
    [Fact]
    public void Allowed_transitions()
    {
        Assert.True(HumanReview.CanTransition(HumanReview.Draft, HumanReview.PendingReview));
        Assert.True(HumanReview.CanTransition(HumanReview.PendingReview, HumanReview.Approved));
        Assert.True(HumanReview.CanTransition(HumanReview.PendingReview, HumanReview.Rejected));
        Assert.True(HumanReview.CanTransition(HumanReview.Rejected, HumanReview.PendingReview));
    }

    [Fact]
    public void Disallowed_transitions()
    {
        Assert.False(HumanReview.CanTransition(HumanReview.Approved, HumanReview.Draft));
        Assert.False(HumanReview.CanTransition(HumanReview.Approved, HumanReview.Rejected));
        Assert.False(HumanReview.CanTransition(HumanReview.Draft, HumanReview.Approved));
    }

    [Fact]
    public void Transition_raises_on_illegal()
    {
        Assert.Throws<InvalidReviewTransitionException>(() => HumanReview.Transition(HumanReview.Approved, HumanReview.Draft));
    }

    [Fact]
    public void Audit_entry_contains_only_safe_metadata()
    {
        var entry = new ReviewTransitionAuditEntry(
            CorrelationId: "corr-1",
            DealerGroupId: "GROUP-DEMO",
            UserLabel: "Staff S-01",
            Timestamp: "2026-01-05T09:00:00Z",
            PreviousState: "pending_review",
            NewState: "approved",
            ValidatorVerdict: "passed",
            EvidenceCount: 2);
        // Python's `entry.__dict__`: every field by name, as the API serializes them.
        var payload = JsonSerializer.SerializeToNode(entry, PyJson.SerializerOptions)!.AsObject();
        var text = PyText.Lower(payload.ToJsonString(PyJson.SerializerOptions));
        foreach (var forbidden in new[] { "prompt", "completion", "concern_text", "raw_critique", "secret", "token" })
        {
            Assert.DoesNotContain(forbidden, text, StringComparison.Ordinal);
        }
    }

    [Fact]
    public async Task Review_endpoint_round_trip()
    {
        var ct = TestContext.Current.CancellationToken;
        using var client = Conftest.MakeClient(demoResetEnabled: false);
        // First generate a real plan.
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
        Assert.True(rec["status"]?.GetValue<string>() == "ok", rec.ToJsonString());
        using var savedResponse = await client.Client.PostAsJsonAsync(
            "/api/supports/plans",
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
                ["selected_goal"] = "GOAL-lead-response-1",
                ["selected_strategies"] = new JsonArray("ST-lead-response-1"),
                ["recommendation"] = rec["recommendation"]?.DeepClone(),
                ["dealer_group_id"] = "GROUP-DEMO",
            },
            ct);
        var saved = (await savedResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!;
        var planId = saved["plan_id"]!.GetValue<string>();
        Assert.Equal("pending_review", saved["human_review_state"]!.GetValue<string>());

        using var approvedResponse = await client.Client.PostAsJsonAsync(
            $"/api/supports/plans/{planId}/review",
            new JsonObject { ["to_state"] = "approved", ["user_label"] = "Staff S-01" },
            ct);
        var approved = (await approvedResponse.Content.ReadFromJsonAsync<JsonNode>(ct))!;
        Assert.Equal("approved", approved["human_review_state"]!.GetValue<string>());

        // Illegal transition returns 409.
        using var bad = await client.Client.PostAsJsonAsync(
            $"/api/supports/plans/{planId}/review",
            new JsonObject { ["to_state"] = "rejected", ["user_label"] = "Staff S-01" },
            ct);
        Assert.Equal(409, (int)bad.StatusCode);
    }
}
