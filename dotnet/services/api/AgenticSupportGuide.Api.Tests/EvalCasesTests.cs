using System.Text;
using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.Parity;
using Microsoft.AspNetCore.Http;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Guards the eval case file against drift from the API contract.</summary>
/// <remarks>
/// The cases are exercised by hand today, so nothing else catches a case that
/// would 422 or hit a dealer group/category with no evidence fixtures.
/// </remarks>
public sealed class EvalCasesTests
{
    private static readonly string CasesPath = Path.Combine(Conformance.Goldens.RepoRoot, "evals", "synthetic_cases.jsonl");

    private static List<JsonObject> Cases()
    {
        var lines = PyText.SplitLines(File.ReadAllText(CasesPath, Encoding.UTF8));
        return [.. lines.Where(line => PyText.Strip(line).Length > 0).Select(line => JsonNode.Parse(line)!.AsObject())];
    }

    // One row per case, carried as its JSON text because xUnit can only list
    // rows it can serialize, and labelled with the case's "id" as pytest's
    // `ids=` labels it: `Case_resolves_to_real_evidence [eval-001]`.
    public static TheoryData<string> CaseRows()
    {
        var rows = new TheoryData<string>();
        foreach (var c in Cases())
        {
            rows.Add(new TheoryDataRow<string>(c.ToJsonString()) { Label = c["id"]!.ToString() });
        }
        return rows;
    }

    // Pydantic validates SupportPlanRequest on construction. This track
    // validates a request body as the endpoint reads it, returning null and
    // naming the failing fields where Pydantic raises.
    private static async Task<SupportPlanRequest?> ParseSupportPlanRequestAsync(JsonObject body, List<string> errors)
    {
        var context = new DefaultHttpContext();
        context.Request.ContentType = "application/json";
        context.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes(body.ToJsonString()));
        return RequestModels.ParseSupportPlanRequest(await JsonBody.ReadAsync(context), errors);
    }

    [Fact]
    public void Cases_file_is_not_empty()
    {
        Assert.NotEmpty(Cases());
    }

    [Theory]
    [MemberData(nameof(CaseRows))]
    public async Task Case_satisfies_the_request_contract(string caseJson)
    {
        var @case = JsonNode.Parse(caseJson)!.AsObject();
        var errors = new List<string>();
        var request = await ParseSupportPlanRequestAsync(
            new JsonObject
            {
                ["dealership_id"] = @case["dealership_id"]!.DeepClone(),
                ["category"] = @case["category"]!.DeepClone(),
                ["concern_text"] = @case["concern_text"]!.DeepClone(),
                ["dealer_group_id"] = @case["dealer_group_id"]!.DeepClone(),
            },
            errors);
        // Constructing the Pydantic model must not raise.
        Assert.Empty(errors);
        Assert.NotNull(request);
    }

    [Theory]
    [MemberData(nameof(CaseRows))]
    public async Task Case_resolves_to_real_evidence(string caseJson)
    {
        var @case = JsonNode.Parse(caseJson)!.AsObject();
        Assert.Contains(@case["category"]!.GetValue<string>(), MockData.CategoryIds);
        var bundle = await new FixtureEvidenceRetriever().RetrieveAsync(
            new EvidenceRequest(
                DealerGroupId: @case["dealer_group_id"]!.GetValue<string>(),
                Category: @case["category"]!.GetValue<string>(),
                DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.NotEmpty(bundle.Citations);
    }
}
