using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api;

/// <summary>Dashboard KPI aggregation.</summary>
public static class Dashboard
{
    public static DashboardSummary BuildSummary(
        IReadOnlyList<Dealership> dealerships,
        IReadOnlyList<AreaScoreRecord> areaScores,
        IReadOnlyList<OperationsRecord> operations) =>
        new(
            KpiCards: KpiCards(dealerships),
            ProcessScoreTrend: MeanByInt(areaScores, r => r.Period, r => r.Score).Select(p => new TrendPoint(p.Key, p.Value)).ToList(),
            AreaDistribution: MeanByInt(areaScores, r => r.ProcessArea, r => r.Score).Select(p => new AreaSlice(p.Key, p.Value)).ToList(),
            EngagementTrend: MeanBy(operations, r => r.Period, r => r.FollowupCompletion).Select(p => new TrendPoint(p.Key, p.Value)).ToList(),
            Notes:
            [
                "All values are synthetic and generated locally.",
                "Trends are illustrative only; not real benchmarks or determinations.",
            ]);

    /// <summary>
    /// Group by <paramref name="key"/>, average <paramref name="value"/>, return pairs sorted by key.
    /// </summary>
    /// <remarks>
    /// Period labels sort chronologically because they are ISO-style "2026-04",
    /// so sorting the keys is enough to order a trend line.
    /// </remarks>
    private static List<KeyValuePair<string, double>> MeanBy<T>(IEnumerable<T> records, Func<T, string> key, Func<T, double> value) =>
        Group(records, key, value)
            .Select(kv => KeyValuePair.Create(kv.Key, PyFloat.Round(PyFloat.Mean(kv.Value), 1)))
            .ToList();

    // Integer values are summed exactly, as Python sums ints, before dividing.
    private static List<KeyValuePair<string, double>> MeanByInt<T>(IEnumerable<T> records, Func<T, string> key, Func<T, int> value) =>
        Group(records, key, value)
            .Select(kv => KeyValuePair.Create(kv.Key, PyFloat.Round((double)kv.Value.Sum(v => (long)v) / kv.Value.Count, 1)))
            .ToList();

    private static IEnumerable<KeyValuePair<string, List<TValue>>> Group<T, TValue>(IEnumerable<T> records, Func<T, string> key, Func<T, TValue> value)
    {
        var grouped = new Dictionary<string, List<TValue>>();
        foreach (var record in records)
        {
            var k = key(record);
            if (!grouped.TryGetValue(k, out var list))
            {
                grouped[k] = list = [];
            }
            list.Add(value(record));
        }
        return grouped.OrderBy(kv => kv.Key, StringComparer.Ordinal);
    }

    private static List<KpiCard> KpiCards(IReadOnlyList<Dealership> dealerships)
    {
        var total = dealerships.Count;
        var flagged = dealerships.Count(d => d.Flagged);
        // The caller passes the full roster today, but a filtered one would make
        // these divisions fail. Guard them like the score band distribution does.
        var avgProcessScore = total > 0 ? PyFloat.Round(PyFloat.Sum(dealerships.Select(d => d.ProcessScore)) / total, 1) : 0.0;
        var avgAttendance = total > 0 ? PyFloat.Round(PyFloat.Sum(dealerships.Select(d => d.AppointmentAttendanceRate)) / total * 100, 1) : 0.0;

        // The deltas are fixed illustrative values. The fixtures hold a single
        // snapshot, so there is no prior period to compare against.
        return
        [
            new KpiCard("kpi-dealerships", "Active Dealerships", total, "count", 0.0, "steady"),
            new KpiCard("kpi-flagged", "Flagged for Support", flagged, "count", PyFloat.Round((double)flagged / total * 100, 1), "watch"),
            new KpiCard("kpi-process-score", "Avg Process Score", avgProcessScore, "index", 1.2, "up"),
            new KpiCard("kpi-appointments", "Appointments Attended", avgAttendance, "percent", -0.4, "down"),
        ];
    }
}
