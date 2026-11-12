using AgenticSupportGuide.Api.Evidence;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Every category the UI can offer must have evidence in every dealer group.</summary>
/// <remarks>
/// The recommendation contract requires at least one citation, so a category
/// with no fixtures can never produce a valid plan - it fails at protocol
/// validation instead. This test makes that gap loud.
/// </remarks>
public sealed class EvidenceCoverageTests
{
    // Both parametrize marks, stacked as pytest stacks them: the category (the
    // mark nearest the function) varies slowest, the dealer group fastest.
    public static TheoryData<string, string> DealerGroupAndCategoryCases()
    {
        var cases = new TheoryData<string, string>();
        foreach (var category in MockData.CategoryIds)
        {
            foreach (var dealerGroupId in FixtureEvidenceRetriever.ListAvailableDealerGroups())
            {
                cases.Add(dealerGroupId, category);
            }
        }
        return cases;
    }

    [Theory]
    [MemberData(nameof(DealerGroupAndCategoryCases))]
    public async Task Every_dealer_group_has_evidence_for_every_category(string dealerGroupId, string category)
    {
        var bundle = await new FixtureEvidenceRetriever().RetrieveAsync(
            new EvidenceRequest(DealerGroupId: dealerGroupId, Category: category, DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.True(bundle.Citations.Count > 0, $"no evidence fixtures for {dealerGroupId}/{category}");
    }

    [Theory]
    [MemberData(nameof(DealerGroupAndCategoryCases))]
    public async Task Citations_never_cross_dealer_groups(string dealerGroupId, string category)
    {
        var bundle = await new FixtureEvidenceRetriever().RetrieveAsync(
            new EvidenceRequest(DealerGroupId: dealerGroupId, Category: category, DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.True(bundle.Citations.All(c => c.DealerGroupId == dealerGroupId));
    }
}
