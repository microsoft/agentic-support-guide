using System.Globalization;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api;

/// <summary>
/// Deterministic mock data factories.
/// </summary>
/// <remarks>
/// All randomness is seeded via <c>new PyRandom(Seed)</c> - the same
/// generator, seed and draw order as the Python track, so both produce
/// byte-identical data. All timestamps derive from <c>BaseTimestamp</c> with
/// fixed offsets so two invocations produce identical JSON.
/// </remarks>
public static class MockData
{
    public static readonly IReadOnlyList<string> RegionIds = ["REG-001", "REG-002", "REG-003", "REG-004"];
    public static readonly IReadOnlyList<string> SegmentIds = ["SEG-VOLUME", "SEG-PREMIUM", "SEG-COMMERCIAL"];

    // Five measured process areas. `multi-area` is deliberately NOT here: it is a
    // plan scope a user can request, not something a dealership is scored on.
    // Scoring it produced a sixth "area" with its own independent value that sat
    // outside the real five for 37 of 120 dealerships and skewed every aggregate.
    public static readonly IReadOnlyList<string> ProcessAreas =
    [
        "lead-response",
        "test-drive-conversion",
        "listing-completeness",
        "inventory-ageing",
        "price-data-freshness",
    ];

    // Everything a plan can be requested for: the measured areas plus the
    // cross-area scope.
    public static readonly IReadOnlyList<string> CategoryIds = [.. ProcessAreas, "multi-area"];

    // Points per period the whole network gains. Individual drifts are centred and
    // so cancel in aggregate, which left every dashboard trend line flat.
    public const double CohortDriftPerPeriod = 0.9;

    // Six consecutive months ending at the current reporting month.
    public const int PeriodStartMonth = 4;

    /// <summary>Roll into the next year rather than emitting "2026-13".</summary>
    public static string PeriodLabel(int index)
    {
        var month = PeriodStartMonth + index;
        var year = 2026 + Math.DivRem(month - 1, 12, out var rem);
        return $"{year}-{rem + 1:00}";
    }

    public static string OffsetIso(int days, int seconds = 0)
    {
        var ts = BaseTime().AddDays(days).AddSeconds(seconds);
        return ts.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
    }

    private static DateTime BaseTime() =>
        DateTime.ParseExact(Config.BaseTimestamp, "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);

    private static string BandLabel(long score)
    {
        if (score < 40)
        {
            return "At risk";
        }
        if (score < 60)
        {
            return "Developing";
        }
        if (score < 80)
        {
            return "On track";
        }
        return "Leading";
    }

    public static List<Dealership> BuildDealerships()
    {
        var rng = new PyRandom(Config.Seed);
        var dealerships = new List<Dealership>();
        for (var i = 1; i <= Config.Counts.Dealerships; i++)
        {
            var region = RegionIds[rng.RandRange(RegionIds.Count)];
            var segment = SegmentIds[rng.RandRange(SegmentIds.Count)];
            var processScore = PyFloat.Round(rng.Uniform(20.0, 95.0), 1);
            var attendance = PyFloat.Round(rng.Uniform(0.72, 0.99), 3);
            var followup = PyFloat.Round(rng.Uniform(30.0, 95.0), 1);
            var engagement = PyFloat.Round(rng.Uniform(30.0, 95.0), 1);
            var flagged = processScore < 45 || attendance < 0.85 || followup < 50;
            dealerships.Add(new Dealership(
                DealershipId: $"DLR-{i:0000}",
                DisplayLabel: $"Dealership {i:0000}",
                RegionId: region,
                Segment: segment,
                ProcessScore: processScore,
                AppointmentAttendanceRate: attendance,
                FollowupIndex: followup,
                EngagementIndex: engagement,
                Flagged: flagged));
        }
        return dealerships;
    }

    /// <summary>
    /// One record per dealership, per period, per process area.
    /// </summary>
    /// <remarks>
    /// This used to draw a random subject and a random area 400 times, which
    /// left 253 of 319 subject-periods holding a single area, 18 holding the
    /// same area twice, and not one holding all six. Nothing could compare a
    /// dealership across areas, which is the analysis the workshop demonstrates.
    ///
    /// Scores are built from a per-dealership baseline, a per-area offset and a
    /// per-dealership drift, so a trend is actually present to be found rather
    /// than being noise.
    /// </remarks>
    public static List<AreaScoreRecord> BuildAreaScores(IReadOnlyList<Dealership> dealerships)
    {
        var rng = new PyRandom(Config.Seed + 1);
        var records = new List<AreaScoreRecord>();
        var sequence = 0;
        foreach (var dealership in dealerships)
        {
            // Compressed into a mid band so an area offset plus six periods of
            // drift still fit inside 1-99. Using the raw score pinned strong
            // dealerships against the ceiling and flattened the trend away.
            var baseline = 28.0 + ((dealership.ProcessScore - 20.0) / 75.0 * 50.0);
            var areaOffsets = new Dictionary<string, double>();
            foreach (var area in ProcessAreas)
            {
                areaOffsets[area] = rng.Uniform(-11.0, 11.0);
            }
            var drift = rng.Uniform(-2.5, 2.5);
            var midpoint = (Config.Counts.ScorePeriods - 1) / 2.0;
            for (var index = 0; index < Config.Counts.ScorePeriods; index++)
            {
                var period = PeriodLabel(index);
                foreach (var area in ProcessAreas)
                {
                    // Drift is centred on the midpoint so process_score stays the
                    // dealership's average rather than their starting point. That
                    // halves the headroom a trend needs, which is what let the
                    // score band stay wide enough to populate every tier.
                    var raw = baseline
                        + areaOffsets[area]
                        + ((drift + CohortDriftPerPeriod) * (index - midpoint))
                        + rng.Uniform(-2.5, 2.5);
                    var score = Math.Max(1, Math.Min(99, PyFloat.RoundToInt(raw)));
                    sequence++;
                    records.Add(new AreaScoreRecord(
                        RecordId: $"SCR-{sequence:00000}",
                        DealershipId: dealership.DealershipId,
                        RegionId: dealership.RegionId,
                        Segment: dealership.Segment,
                        ProcessArea: area,
                        Band: BandLabel(score),
                        Score: (int)score,
                        Period: period));
                }
            }
        }
        return records;
    }

    /// <summary>
    /// One record per dealership, per period.
    /// </summary>
    /// <remarks>
    /// This used to draw 150 records at random across 720 dealership-periods, so
    /// a typical dealership had a single data point and the analyst could not see
    /// an operational trend at all.
    /// </remarks>
    public static List<OperationsRecord> BuildOperations(IReadOnlyList<Dealership> dealerships)
    {
        var rng = new PyRandom(Config.Seed + 2);
        var records = new List<OperationsRecord>();
        var sequence = 0;
        var midpoint = (Config.Counts.ScorePeriods - 1) / 2.0;
        foreach (var dealership in dealerships)
        {
            var attendanceDrift = rng.Uniform(-0.015, 0.015);
            var followupDrift = rng.Uniform(-2.0, 2.0);
            for (var index = 0; index < Config.Counts.ScorePeriods; index++)
            {
                var offset = index - midpoint;
                var attendance = dealership.AppointmentAttendanceRate + (attendanceDrift * offset);
                attendance += rng.Uniform(-0.01, 0.01);
                var followup = dealership.FollowupIndex + (followupDrift * offset) + rng.Uniform(-2.0, 2.0);
                sequence++;
                var record = new OperationsRecord(
                    RecordId: $"OPS-{sequence:00000}",
                    DealershipId: dealership.DealershipId,
                    RegionId: dealership.RegionId,
                    Period: PeriodLabel(index),
                    AppointmentAttendanceRate: PyFloat.Round(Math.Max(0.5, Math.Min(1.0, attendance)), 3),
                    Escalations: rng.RandRange(0, 5),
                    FollowupCompletion: PyFloat.Round(Math.Max(1.0, Math.Min(99.0, followup)), 1));
                records.Add(record);
            }
        }
        return records;
    }

    public static List<ResourceItem> BuildResources()
    {
        var rng = new PyRandom(Config.Seed + 3);
        string[] kinds = ["playbook", "checklist", "coaching-plan", "customer-message", "audit-kit"];
        string[] tiers = ["baseline", "focused", "intensive"];
        var items = new List<ResourceItem>();
        for (var i = 1; i <= Config.Counts.Resources; i++)
        {
            var area = ProcessAreas[rng.RandRange(ProcessAreas.Count)];
            var kind = kinds[rng.RandRange(kinds.Length)];
            var tier = tiers[rng.RandRange(tiers.Length)];
            items.Add(new ResourceItem(
                ResourceId: $"RES-{i:000}",
                Label: $"Process Kit {i:000}",
                Kind: kind,
                ProcessArea: area,
                Tier: tier));
        }
        return items;
    }

    public static List<AuditRow> BuildAuditRows()
    {
        var rng = new PyRandom(Config.Seed + 4);
        string[] endpoints =
        [
            "/api/dashboard/summary",
            "/api/scores/summary",
            "/api/recommendations/support-plan",
            "/api/supports/plans",
            "/api/operations/summary",
            "/api/dealerships",
        ];
        string[] statuses = ["ok", "ok", "ok", "ok", "warning", "error"];
        string[] contexts =
        [
            "dashboard-refresh",
            "filter-change",
            "plan-generation",
            "plan-save",
            "dealership-listing",
            "trend-review",
        ];
        var rows = new List<AuditRow>();
        for (var i = 1; i <= Config.Counts.AuditEvents; i++)
        {
            var ep = endpoints[rng.RandRange(endpoints.Length)];
            var ctx = contexts[rng.RandRange(contexts.Length)];
            var status = statuses[rng.RandRange(statuses.Length)];
            var duration = rng.RandRange(35, 480);
            var tokens = rng.RandRange(0, 900);
            var user = $"S-{rng.RandRange(1, 21):00}";
            rows.Add(new AuditRow(
                EventId: $"AUD-{i:0000}",
                Timestamp: OffsetIso(days: i / 5, seconds: i * 137),
                Endpoint: ep,
                Context: ctx,
                User: user,
                ProviderModel: "local-rules / mock-reasoner-v0",
                DurationMs: duration,
                TokenEstimate: tokens,
                Status: status));
        }
        return rows;
    }

    public static List<SeededPlanSpec> BuildSeededPlanSpecs()
    {
        var rng = new PyRandom(Config.Seed + 5);
        var concerns = new Dictionary<string, string>
        {
            ["lead-response"] = "Median first response to online enquiries slipped past one hour.",
            ["test-drive-conversion"] = "Booked test drives are attended less often than last quarter.",
            ["listing-completeness"] = "Listings are publishing without required photos and label data.",
            ["inventory-ageing"] = "Scheduled ageing reviews are being missed on part of the stock.",
            ["price-data-freshness"] = "Advertised prices are not being refreshed on the agreed cadence.",
            ["multi-area"] = "Enquiry handling, test drives, and listing quality all declined.",
        };
        var specs = new List<SeededPlanSpec>();
        for (var i = 1; i <= Config.Counts.SeededPlans; i++)
        {
            var category = CategoryIds[rng.RandRange(CategoryIds.Count)];
            var dealershipNum = rng.RandRange(1, Config.Counts.Dealerships + 1);
            specs.Add(new SeededPlanSpec(
                PlanId: $"PLN-{i:0000}",
                DealershipId: $"DLR-{dealershipNum:0000}",
                Category: category,
                ConcernText: concerns[category],
                SelectedGoalId: $"GOAL-{category}-1",
                SelectedStrategyIds: [$"ST-{category}-1", $"ST-{category}-2"],
                CreatedAt: OffsetIso(days: i, seconds: i * 91)));
        }
        return specs;
    }
}

public sealed record Dealership(
    string DealershipId,
    string DisplayLabel,
    string RegionId,
    string Segment,
    double ProcessScore,
    double AppointmentAttendanceRate,
    double FollowupIndex,
    double EngagementIndex,
    bool Flagged);

public sealed record AreaScoreRecord(
    string RecordId,
    string DealershipId,
    string RegionId,
    string Segment,
    string ProcessArea,
    string Band,
    int Score,
    string Period);

public sealed record OperationsRecord(
    string RecordId,
    string DealershipId,
    string RegionId,
    string Period,
    double AppointmentAttendanceRate,
    int Escalations,
    double FollowupCompletion);

public sealed record ResourceItem(string ResourceId, string Label, string Kind, string ProcessArea, string Tier);

public sealed record AuditRow(
    string EventId,
    string Timestamp,
    string Endpoint,
    string Context,
    string User,
    string ProviderModel,
    int DurationMs,
    int TokenEstimate,
    string Status);

public sealed record SeededPlanSpec(
    string PlanId,
    string DealershipId,
    string Category,
    string ConcernText,
    string? SelectedGoalId,
    IReadOnlyList<string> SelectedStrategyIds,
    string CreatedAt);
