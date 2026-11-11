using System.Reflection;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Concurrency and retention guards for the in-memory stores.
/// </summary>
/// <remarks>
/// ASP.NET Core serves requests on the thread pool, so these stores are hit
/// concurrently. They are also process-lifetime objects, so they must not grow
/// without bound.
/// </remarks>
public sealed class StoreLimitsTests
{
    // The store's own seeded stub. It is private to SavedPlansStore, so it is
    // reached by reflection.
    private static Recommendation StubRecommendation(string category) =>
        (Recommendation)typeof(SavedPlansStore)
            .GetMethod("StubRecommendation", BindingFlags.NonPublic | BindingFlags.Static)!
            .Invoke(null, [category])!;

    private static SavedPlan Plan(string planId) => new(
        PlanId: planId,
        DealershipId: "DLR-0001",
        DealerGroupId: "GROUP-A",
        Category: "lead-response",
        ConcernText: "synthetic concern",
        SelectedGoal: "",
        SelectedStrategies: [],
        CreatedAt: "2026-01-05T09:00:00Z",
        Recommendation: StubRecommendation("lead-response"),
        HumanReviewState: "pending_review");

    [Fact]
    public void Next_plan_id_is_unique_under_concurrency()
    {
        var store = new SavedPlansStore();
        var ids = Enumerable.Range(0, 500)
            .AsParallel()
            .WithDegreeOfParallelism(16)
            .WithCancellation(TestContext.Current.CancellationToken)
            .Select(_ => store.NextPlanId())
            .ToList();
        Assert.Equal(ids.Count, ids.ToHashSet().Count);
    }

    [Fact]
    public void Saved_plans_store_is_bounded()
    {
        var store = new SavedPlansStore(maxPlans: 5);
        for (var i = 0; i < 50; i++)
        {
            store.Add(Plan(store.NextPlanId()));
        }
        Assert.Equal(5, store.List().Count);
    }
}
