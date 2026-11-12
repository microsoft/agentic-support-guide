namespace AgenticSupportGuide.Api;

/// <summary>In-memory repositories built once at startup.</summary>
public sealed record Repositories(
    IReadOnlyList<Dealership> Dealerships,
    IReadOnlyList<AreaScoreRecord> AreaScores,
    IReadOnlyList<OperationsRecord> Operations,
    IReadOnlyList<ResourceItem> Resources,
    IReadOnlyList<AuditRow> Audit,
    IReadOnlyList<SeededPlanSpec> SeededPlans)
{
    public static Repositories Build()
    {
        var dealerships = MockData.BuildDealerships();
        return new Repositories(
            Dealerships: dealerships,
            AreaScores: MockData.BuildAreaScores(dealerships),
            Operations: MockData.BuildOperations(dealerships),
            Resources: MockData.BuildResources(),
            Audit: MockData.BuildAuditRows(),
            SeededPlans: MockData.BuildSeededPlanSpecs());
    }
}

/// <summary>Dealership query module.</summary>
public static class Dealerships
{
    public static DealershipsResponse ListDealershipSummaries(IReadOnlyList<Dealership> dealerships)
    {
        var summaries = dealerships
            .Select(d => new DealershipSummary(
                d.DealershipId,
                d.DisplayLabel,
                d.RegionId,
                d.Segment,
                d.ProcessScore,
                d.AppointmentAttendanceRate,
                d.FollowupIndex,
                d.EngagementIndex,
                d.Flagged))
            .ToList();
        return new DealershipsResponse(summaries, summaries.Count);
    }
}

/// <summary>
/// The dealer group roster for the synthetic workshop dataset.
/// </summary>
/// <remarks>
/// One definition, because three places need the same answer: the supports
/// endpoint rejects an unknown group against it, diagnostics checks evidence
/// coverage, and the UI offers it as a picker. When these drifted apart the UI
/// simply hardcoded <c>GROUP-DEMO</c>.
///
/// A dealer group is an ownership boundary, not a franchise brand: one group
/// may sell several brands, and two groups selling the same brand must never
/// see each other's data.
///
/// Replacing the mock data means replacing this with a lookup against the real
/// group registry.
/// </remarks>
public static class DealerGroups
{
    public static readonly IReadOnlyList<string> KnownDealerGroups = ["GROUP-A", "GROUP-B", "GROUP-DEMO"];

    // Seeded plans and the guided builder default here.
    public const string DemoDealerGroup = "GROUP-DEMO";
}
