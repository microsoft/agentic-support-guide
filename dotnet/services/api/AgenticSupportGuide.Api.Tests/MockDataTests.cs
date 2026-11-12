using System.Text;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

public sealed class MockDataTests
{
    [Fact]
    public void Counts_match_spec()
    {
        var dealerships = MockData.BuildDealerships();
        Assert.Equal(Config.Counts.Dealerships, dealerships.Count);
        Assert.Equal(
            Config.Counts.Dealerships * Config.Counts.ScorePeriods * MockData.ProcessAreas.Count,
            MockData.BuildAreaScores(dealerships).Count);
        Assert.Equal(Config.Counts.Dealerships * Config.Counts.ScorePeriods, MockData.BuildOperations(dealerships).Count);
        Assert.Equal(Config.Counts.Resources, MockData.BuildResources().Count);
        Assert.Equal(Config.Counts.AuditEvents, MockData.BuildAuditRows().Count);
        Assert.Equal(Config.Counts.SeededPlans, MockData.BuildSeededPlanSpecs().Count);
    }

    /// <summary>A random 150 records over 720 slots gave most dealerships one datapoint.</summary>
    /// <remarks>
    /// One datapoint cannot show a trend, so the analyst had nothing operational
    /// to reason about.
    /// </remarks>
    [Fact]
    public void Every_dealership_has_an_operations_record_for_every_period()
    {
        var dealerships = MockData.BuildDealerships();
        var seen = MockData.BuildOperations(dealerships).Select(r => (r.DealershipId, r.Period)).ToHashSet();
        Assert.Equal(Config.Counts.Dealerships * Config.Counts.ScorePeriods, seen.Count);
        Assert.True(dealerships.Select(d => d.DealershipId).ToHashSet().SetEquals(seen.Select(key => key.DealershipId)));
    }

    /// <summary>The dataset claims every review scores every area; it did not.</summary>
    /// <remarks>
    /// Random sampling left 253 of 319 subject-periods holding a single area
    /// and none holding all six, so no cross-area comparison was possible.
    /// </remarks>
    [Fact]
    public void Every_dealership_period_scores_every_area_exactly_once()
    {
        var dealerships = MockData.BuildDealerships();
        var groups = new Dictionary<(string DealershipId, string Period), List<string>>();
        foreach (var record in MockData.BuildAreaScores(dealerships))
        {
            var key = (record.DealershipId, record.Period);
            if (!groups.TryGetValue(key, out var areas))
            {
                groups[key] = areas = [];
            }
            areas.Add(record.ProcessArea);
        }

        Assert.Equal(Config.Counts.Dealerships * Config.Counts.ScorePeriods, groups.Count);
        Assert.True(dealerships.Select(d => d.DealershipId).ToHashSet().SetEquals(groups.Keys.Select(key => key.DealershipId)));
        foreach (var (key, areas) in groups)
        {
            // Counter equality: the same areas, each the same number of times.
            Assert.True(
                areas.Order(StringComparer.Ordinal).SequenceEqual(MockData.ProcessAreas.Order(StringComparer.Ordinal)),
                $"incomplete or duplicated: ({PyText.Repr(key.DealershipId)}, {PyText.Repr(key.Period)})");
        }
    }

    /// <summary>A flat random series gives the analyst agent nothing to detect.</summary>
    [Fact]
    public void Scores_carry_a_trend_rather_than_noise()
    {
        var dealerships = MockData.BuildDealerships();
        var byDealership = new Dictionary<string, Dictionary<string, List<int>>>();
        foreach (var record in MockData.BuildAreaScores(dealerships))
        {
            if (!byDealership.TryGetValue(record.DealershipId, out var periods))
            {
                byDealership[record.DealershipId] = periods = [];
            }
            if (!periods.TryGetValue(record.Period, out var scores))
            {
                periods[record.Period] = scores = [];
            }
            scores.Add(record.Score);
        }

        var deltas = new List<double>();
        foreach (var periods in byDealership.Values)
        {
            var ordered = periods
                .OrderBy(kv => kv.Key, StringComparer.Ordinal)
                .Select(kv => (double)kv.Value.Sum() / kv.Value.Count)
                .ToList();
            deltas.Add(ordered[^1] - ordered[0]);
        }

        // Both directions must occur, or the demo only ever tells one story.
        Assert.True(deltas.Any(delta => delta >= 5.0), "no dealership improves");
        Assert.True(deltas.Any(delta => delta <= -5.0), "no dealership declines");
        var moved = deltas.Count(delta => Math.Abs(delta) >= 5.0);
        Assert.True(moved >= deltas.Count / 3, $"only {moved} of {deltas.Count} dealerships move");
    }

    /// <summary>Saturating at 99 flattened strong dealerships into a straight line.</summary>
    [Fact]
    public void Scores_stay_off_the_clamp_bounds()
    {
        var records = MockData.BuildAreaScores(MockData.BuildDealerships());
        Assert.DoesNotContain(records, r => r.Score is 1 or 99);
    }

    /// <summary>Centred per-dealership drift cancels out and flattened every trend chart.</summary>
    [Fact]
    public void The_cohort_average_moves_across_periods()
    {
        var byPeriod = new Dictionary<string, List<int>>();
        foreach (var record in MockData.BuildAreaScores(MockData.BuildDealerships()))
        {
            if (!byPeriod.TryGetValue(record.Period, out var scores))
            {
                byPeriod[record.Period] = scores = [];
            }
            scores.Add(record.Score);
        }
        var means = byPeriod
            .OrderBy(kv => kv.Key, StringComparer.Ordinal)
            .Select(kv => (double)kv.Value.Sum() / kv.Value.Count)
            .ToList();
        Assert.True(means[^1] - means[0] >= 3.0, $"cohort trend is flat: [{string.Join(", ", means.Select(PyFloat.Repr))}]");
    }

    [Fact]
    public void Two_invocations_produce_identical_json()
    {
        // Python dumps each dataclass's __dict__; the records serialize to the
        // same snake_case fields. PyJson has no `separators` option, so the
        // snapshot keeps json.dumps' default spacing, sorted as Python sorts it.
        static string Snapshot()
        {
            var dealerships = MockData.BuildDealerships();
            var payload = new Dictionary<string, object>
            {
                ["dealerships"] = dealerships,
                ["assessments"] = MockData.BuildAreaScores(dealerships),
                ["behavior"] = MockData.BuildOperations(dealerships),
                ["resources"] = MockData.BuildResources(),
                ["audit"] = MockData.BuildAuditRows(),
                ["seeded_plans"] = MockData.BuildSeededPlanSpecs(),
            };
            return PyJson.Dumps(payload, sortKeys: true);
        }

        var first = Snapshot();
        var second = Snapshot();
        Assert.True(first == second, "Mock data factories must be deterministic");
        Assert.Equal(Encoding.UTF8.GetBytes(first), Encoding.UTF8.GetBytes(second));
    }

    [Fact]
    public void Dealership_ids_are_synthetic()
    {
        foreach (var dealership in MockData.BuildDealerships())
        {
            Assert.StartsWith("DLR-", dealership.DealershipId, StringComparison.Ordinal);
            Assert.StartsWith("Dealership ", dealership.DisplayLabel, StringComparison.Ordinal);
        }
    }
}
