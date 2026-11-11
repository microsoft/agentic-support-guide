using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api;

/// <summary>
/// One dealership's score history, per process area, in period order.
/// </summary>
/// <remarks>
/// <c>ScoresByArea</c> values line up positionally with <c>Periods</c>, and a
/// gap is <c>null</c> rather than a shortened list. A shortened list silently
/// shifted later readings into earlier slots, so a June score read as May.
/// </remarks>
public sealed record AreaSeries(
    IReadOnlyList<string> Periods,
    IReadOnlyDictionary<string, IReadOnlyList<int?>> ScoresByArea,
    IReadOnlyDictionary<string, string> LatestBandByArea,
    int RecordCount,
    int DuplicateCount = 0)
{
    public bool IsEmpty() => Periods.Count == 0;
}

/// <summary>Process-area score aggregation module.</summary>
public static class Scores
{
    public static readonly IReadOnlyList<string> BandOrder = ["At risk", "Developing", "On track", "Leading"];

    // The table is a preview, not an export. Returning 3600 rows to a browser to
    // render a scrollable grid is not worth the payload.
    public const int MaxTableRows = 100;

    /// <summary>
    /// The per-area time series the analyst reasons over.
    /// </summary>
    /// <remarks>
    /// The analyst used to receive only a record *count*, so the cross-area and
    /// temporal comparison its instructions describe had nothing to work from.
    /// </remarks>
    public static AreaSeries SeriesFor(IReadOnlyList<AreaScoreRecord> records, string dealershipId)
    {
        var rows = records.Where(r => r.DealershipId == dealershipId).ToList();
        var periods = rows.Select(r => r.Period).Distinct().Order(StringComparer.Ordinal).ToList();
        var byArea = new Dictionary<string, Dictionary<string, AreaScoreRecord>>();
        var duplicates = 0;
        foreach (var row in rows)
        {
            if (!byArea.TryGetValue(row.ProcessArea, out var byPeriod))
            {
                byArea[row.ProcessArea] = byPeriod = [];
            }
            if (byPeriod.ContainsKey(row.Period))
            {
                duplicates++;
            }
            byPeriod[row.Period] = row;
        }

        var sortedAreas = byArea.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToList();
        var scoresByArea = new Dictionary<string, IReadOnlyList<int?>>();
        var latestBandByArea = new Dictionary<string, string>();
        foreach (var (area, byPeriod) in sortedAreas)
        {
            scoresByArea[area] = periods.Select(p => byPeriod.TryGetValue(p, out var r) ? (int?)r.Score : null).ToList();
        }
        foreach (var (area, byPeriod) in sortedAreas)
        {
            if (periods.Count > 0 && byPeriod.TryGetValue(periods[^1], out var latest))
            {
                latestBandByArea[area] = latest.Band;
            }
        }
        return new AreaSeries(periods, scoresByArea, latestBandByArea, rows.Count, duplicates);
    }

    public static ScoresSummary Summarize(IReadOnlyList<AreaScoreRecord> records, string? region, string? processArea, string? segment)
    {
        var filtered = Filter(records, region, processArea, segment);
        var distribution = BandDistribution(filtered);
        var total = filtered.Count;

        return new ScoresSummary(
            FiltersApplied: new Dictionary<string, string?>
            {
                ["region"] = region,
                ["process_area"] = processArea,
                ["segment"] = segment,
            },
            TotalRecords: total,
            BandDistribution: distribution,
            AreaTrends: AreaTrends(filtered),
            RecommendationBullets: RecommendationBullets(total, distribution),
            PerformanceSummary: PerformanceSummary(total, distribution),
            GeneratedBy: "Generated from local rules over synthetic data.",
            TableRows: TableRows(filtered));
    }

    private static List<AreaScoreRecord> Filter(IReadOnlyList<AreaScoreRecord> records, string? region, string? processArea, string? segment) =>
        records
            .Where(r => (region is null || r.RegionId == region)
                && (processArea is null || r.ProcessArea == processArea)
                && (segment is null || r.Segment == segment))
            .ToList();

    private static List<BandBucket> BandDistribution(List<AreaScoreRecord> records)
    {
        var counts = records.GroupBy(r => r.Band).ToDictionary(g => g.Key, g => g.Count());
        var total = records.Count;
        return BandOrder
            .Select(label =>
            {
                var count = counts.GetValueOrDefault(label, 0);
                return new BandBucket(label, count, total > 0 ? PyFloat.Round((double)count / total * 100, 1) : 0.0);
            })
            .ToList();
    }

    private static List<AreaTrend> AreaTrends(List<AreaScoreRecord> records)
    {
        var byArea = new Dictionary<string, Dictionary<string, List<int>>>();
        foreach (var r in records)
        {
            if (!byArea.TryGetValue(r.ProcessArea, out var periods))
            {
                byArea[r.ProcessArea] = periods = [];
            }
            if (!periods.TryGetValue(r.Period, out var scores))
            {
                periods[r.Period] = scores = [];
            }
            scores.Add(r.Score);
        }
        return byArea
            .OrderBy(kv => kv.Key, StringComparer.Ordinal)
            .Select(kv => new AreaTrend(
                kv.Key,
                kv.Value
                    .OrderBy(p => p.Key, StringComparer.Ordinal)
                    .Select(p => new TrendPoint(p.Key, PyFloat.Round((double)p.Value.Sum(s => (long)s) / p.Value.Count, 1)))
                    .ToList()))
            .ToList();
    }

    private static double Percent(IReadOnlyList<BandBucket> distribution, string label) =>
        distribution.FirstOrDefault(b => b.Label == label)?.Percent ?? 0.0;

    private static string PerformanceSummary(int total, IReadOnlyList<BandBucket> distribution)
    {
        var healthy = Percent(distribution, "On track") + Percent(distribution, "Leading");
        return $"Across {total} synthetic process-score records, {PyFloat.Fixed(healthy, 1)}% " +
            $"are On track or Leading and {PyFloat.Fixed(Percent(distribution, "At risk"), 1)}% are At risk. " +
            "This is illustrative aggregation, not a real benchmark.";
    }

    /// <summary>
    /// Fixed thresholds over the filtered rows. No model is involved.
    /// </summary>
    /// <remarks>
    /// This is what the dashboard shows before anyone asks for a plan, and it is
    /// worth contrasting with the agent workflow: same data, but these bullets
    /// cite no evidence and adapt to nothing.
    /// </remarks>
    private static List<string> RecommendationBullets(int total, IReadOnlyList<BandBucket> distribution)
    {
        var atRisk = Percent(distribution, "At risk");
        var leading = Percent(distribution, "Leading");
        var healthy = Percent(distribution, "On track") + leading;

        var bullets = new List<string>();
        if (atRisk > 25)
        {
            bullets.Add("Consider a focused coaching cycle for dealerships in the At risk band.");
        }
        if (leading > 25)
        {
            bullets.Add("Review what consistently Leading dealerships are doing differently.");
        }
        if (total > 0 && healthy < 40)
        {
            bullets.Add("Fewer than 40% are On track or better; review the process cadence.");
        }
        return bullets.Count > 0 ? bullets : ["No rule-based flags triggered on the current filter selection."];
    }

    private static List<IReadOnlyDictionary<string, object>> TableRows(List<AreaScoreRecord> records) =>
        records
            .Take(MaxTableRows)
            .Select(r => (IReadOnlyDictionary<string, object>)new Dictionary<string, object>
            {
                ["record_id"] = r.RecordId,
                ["dealership_id"] = r.DealershipId,
                ["region_id"] = r.RegionId,
                ["segment"] = r.Segment,
                ["process_area"] = r.ProcessArea,
                ["band"] = r.Band,
                ["score"] = r.Score,
                ["period"] = r.Period,
            })
            .ToList();
}
