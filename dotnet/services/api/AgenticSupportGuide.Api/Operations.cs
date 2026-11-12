using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api;

/// <summary>One dealership's operational history, in period order.</summary>
public sealed record OperationsSeries(
    IReadOnlyList<string> Periods,
    IReadOnlyList<double> AppointmentAttendanceRate,
    IReadOnlyList<int> Escalations,
    IReadOnlyList<double> FollowupCompletion,
    int RecordCount)
{
    public bool IsEmpty() => Periods.Count == 0;
}

/// <summary>Appointment / escalation / follow-up aggregation.</summary>
public static class Operations
{
    /// <summary>The operational time series the analyst reasons over.</summary>
    public static OperationsSeries SeriesFor(IReadOnlyList<OperationsRecord> records, string dealershipId)
    {
        var rows = records.Where(r => r.DealershipId == dealershipId).ToList();
        var byPeriod = new Dictionary<string, List<OperationsRecord>>();
        foreach (var row in rows)
        {
            if (!byPeriod.TryGetValue(row.Period, out var list))
            {
                byPeriod[row.Period] = list = [];
            }
            list.Add(row);
        }
        var periods = byPeriod.Keys.Order(StringComparer.Ordinal).ToList();

        static double Mean(List<double> values) => PyFloat.Round(PyFloat.Mean(values), 3);

        return new OperationsSeries(
            Periods: periods,
            AppointmentAttendanceRate: periods.Select(p => Mean(byPeriod[p].Select(r => r.AppointmentAttendanceRate).ToList())).ToList(),
            Escalations: periods.Select(p => (int)PyFloat.RoundToInt((double)byPeriod[p].Sum(r => (long)r.Escalations) / byPeriod[p].Count)).ToList(),
            FollowupCompletion: periods.Select(p => Mean(byPeriod[p].Select(r => r.FollowupCompletion).ToList())).ToList(),
            RecordCount: rows.Count);
    }

    public static OperationsSummary Summarize(IReadOnlyList<OperationsRecord> records)
    {
        // Rates are stored 0-1 and shown as percentages.
        var attendance = Trend(records, r => r.AppointmentAttendanceRate, scale: 100.0);
        var escalations = Trend(records, r => r.Escalations, digits: 2);
        var followup = Trend(records, r => r.FollowupCompletion);

        var highlights = new List<string>();
        if (attendance.Count > 0)
        {
            highlights.Add($"Average booked appointments attended across periods: {PyFloat.Fixed(Average(attendance), 1)}% (synthetic).");
        }
        if (escalations.Count > 0)
        {
            highlights.Add($"Average escalations per dealership-period: {PyFloat.Fixed(Average(escalations), 2)} (synthetic).");
        }
        if (followup.Count > 0)
        {
            highlights.Add($"Average follow-up completion: {PyFloat.Fixed(Average(followup), 1)} (synthetic).");
        }

        return new OperationsSummary(attendance, escalations, followup, highlights, records.Count);
    }

    private static List<TrendPoint> Trend(IReadOnlyList<OperationsRecord> records, Func<OperationsRecord, double> value, double scale = 1.0, int digits = 1) =>
        Group(records, value)
            .Select(kv => new TrendPoint(kv.Key, PyFloat.Round(PyFloat.Mean(kv.Value) * scale, digits)))
            .ToList();

    // Integer values are summed exactly, as Python sums ints, before dividing.
    private static List<TrendPoint> Trend(IReadOnlyList<OperationsRecord> records, Func<OperationsRecord, int> value, int digits) =>
        Group(records, r => value(r))
            .Select(kv => new TrendPoint(kv.Key, PyFloat.Round((double)kv.Value.Sum(v => (long)v) / kv.Value.Count, digits)))
            .ToList();

    private static IEnumerable<KeyValuePair<string, List<T>>> Group<T>(IReadOnlyList<OperationsRecord> records, Func<OperationsRecord, T> value)
    {
        var byPeriod = new Dictionary<string, List<T>>();
        foreach (var r in records)
        {
            if (!byPeriod.TryGetValue(r.Period, out var list))
            {
                byPeriod[r.Period] = list = [];
            }
            list.Add(value(r));
        }
        return byPeriod.OrderBy(kv => kv.Key, StringComparer.Ordinal);
    }

    private static double Average(List<TrendPoint> points) => PyFloat.Mean(points.Select(p => p.Value).ToList());
}
