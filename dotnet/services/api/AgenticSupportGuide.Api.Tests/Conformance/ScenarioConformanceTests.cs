using System.Text.Json.Nodes;

namespace AgenticSupportGuide.Api.Tests.Conformance;

/// <summary>
/// This track against the behaviour recorded from the Python track.
/// </summary>
/// <remarks>
/// conformance/README.md explains the goldens; anything this track may do
/// differently is listed, with its reason, in allowed_differences.yaml.
/// </remarks>
public class ScenarioConformanceTests
{
    public static TheoryData<string> Scenarios() => [.. Goldens.ScenarioNames()];

    [Theory]
    [MemberData(nameof(Scenarios))]
    public async Task Scenario_matches_the_python_track(string name)
    {
        var golden = Goldens.Load($"scenarios/{name}.json").AsObject();
        var actual = await ScenarioReplay.RunAsync(golden);
        var expectedSteps = golden["steps"]!.AsArray();
        Assert.Equal(expectedSteps.Count, actual.Count);

        var differences = new List<string>();
        for (var i = 0; i < actual.Count; i++)
        {
            var expected = expectedSteps[i]!.AsObject();
            var request = expected["request"]!.AsObject();
            var label = $"step {i} ({request["method"]} {request["path"]})";
            if (ScenarioReplay.IsPreflight(request))
            {
                var want = ScenarioReplay.PreflightAllowed(request, expected["response"]!.AsObject());
                var got = ScenarioReplay.PreflightAllowed(request, actual[i].Response);
                if (want != got)
                {
                    differences.Add($"{label}: browser verdict expected {(want ? "allowed" : "blocked")}, got {(got ? "allowed" : "blocked")}");
                }
            }
            else
            {
                differences.AddRange(JsonCompare.Differences(expected["response"], actual[i].Response, $"{label} response").Take(20));
            }
            differences.AddRange(JsonCompare.Differences(expected["model_calls"], actual[i].ModelCalls, $"{label} model_calls").Take(20));
        }
        Assert.True(differences.Count == 0, string.Join("\n", differences));
    }
}
