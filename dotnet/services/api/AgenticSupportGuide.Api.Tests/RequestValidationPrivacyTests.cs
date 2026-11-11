using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// A rejected request must not echo what was submitted.
/// </summary>
/// <remarks>
/// The framework's default 422 body echoes the offending value. For this API
/// that value is the user's concern text, so the default turns a validation
/// error into a disclosure in the response body and in any log or proxy that
/// records it.
/// </remarks>
public sealed class RequestValidationPrivacyTests
{
    private static readonly string Canary = "CANARY-e3f1a9-do-not-echo-this-text";

    [Fact]
    public async Task Rejected_request_does_not_echo_submitted_text()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "D-001",
                ["category"] = "service",
                // Over the 1000-character limit, so validation rejects the body.
                ["concern_text"] = string.Concat(Enumerable.Repeat(Canary, 60)),
                ["dealer_group_id"] = "GROUP-A",
            },
            TestContext.Current.CancellationToken);

        Assert.Equal(422, (int)response.StatusCode);
        Assert.DoesNotContain(Canary, await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Rejected_request_reports_the_field_that_failed()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await client.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new JsonObject
            {
                ["dealership_id"] = "D-001",
                ["category"] = "service",
                ["concern_text"] = new string('x', 1001),
                ["dealer_group_id"] = "GROUP-A",
            },
            TestContext.Current.CancellationToken);

        var body = (await response.Content.ReadFromJsonAsync<JsonNode>(TestContext.Current.CancellationToken))!;
        Assert.Equal("REQUEST_VALIDATION_FAILED", body["error_code"]!.GetValue<string>());
        Assert.Contains(body["fields"]!.AsArray(), field => field!.GetValue<string>().Contains("concern_text", StringComparison.Ordinal));
    }
}
