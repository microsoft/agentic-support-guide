using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests.Conformance;

/// <summary>
/// The generated data, the composed instructions and the domain rule, against
/// the Python track's recordings - byte for byte where the golden is text.
/// </summary>
public class DataConformanceTests
{
    public static TheoryData<string> DataSets() =>
        ["dealerships", "area_scores", "operations", "resources", "audit_rows", "seeded_plans"];

    [Theory]
    [MemberData(nameof(DataSets))]
    public void Generated_data_is_byte_identical(string name)
    {
        var repos = Repositories.Build();
        object content = name switch
        {
            "dealerships" => repos.Dealerships,
            "area_scores" => Digest(repos.AreaScores),
            "operations" => Digest(repos.Operations),
            "resources" => repos.Resources,
            "audit_rows" => repos.Audit,
            "seeded_plans" => repos.SeededPlans,
            _ => throw new ArgumentOutOfRangeException(nameof(name)),
        };
        Assert.Equal(Goldens.LoadText($"data/{name}.json"), Render(content));
    }

    [Fact]
    public void Composed_instructions_are_identical()
    {
        using var app = TestApp.Start();
        var roles = RoleDefinitions.LoadRoleDefinitions();
        foreach (var role in RoleDefinitions.RequiredRoles)
        {
            Assert.Equal(Goldens.LoadText($"instructions/{role}.txt"), roles[role].Instructions);
        }
    }

    [Fact]
    public void Determination_rule_gives_the_same_verdicts()
    {
        var golden = Goldens.Load("determinations.json").AsObject();
        // The golden is what this track must match, but xUnit wants the constant first.
        Assert.Equal(Determinations.RequiredReviewPhrase, golden["required_review_phrase"]!.GetValue<string>());
        Assert.Equal(Determinations.HumanReviewCaveat, golden["human_review_caveat"]!.GetValue<string>());
        Assert.Equal(Determinations.PolicyNounPhrase, golden["policy_noun_phrase"]!.GetValue<string>());

        var mismatches = new List<string>();
        foreach (var vector in golden["vectors"]!.AsArray())
        {
            var text = vector!["text"]!.GetValue<string>();
            var expected = (
                vector["asserts_determination"]!.GetValue<bool>(),
                vector["denies_human_review"]!.GetValue<bool>(),
                vector["violates"]!.GetValue<bool>());
            var actual = (
                Determinations.AssertsDetermination(text),
                Determinations.DeniesHumanReview(text),
                Determinations.Violates(text));
            if (expected != actual)
            {
                mismatches.Add($"{PyJson.Quote(text)}: expected {expected}, got {actual}");
            }
        }
        Assert.True(mismatches.Count == 0, string.Join("\n", mismatches));
    }

    // The exact bytes a golden is stored as: json.dumps(indent=2, ensure_ascii=False) + "\n".
    private static string Render(object content) => PyJson.Dumps(content, indent: 2, ensureAscii: false) + "\n";

    /// <summary>A large data set as its size, a hash of Python's <c>json.dumps(rows)</c> and the first rows.</summary>
    private static Dictionary<string, object> Digest<T>(IReadOnlyList<T> rows) => new()
    {
        ["count"] = rows.Count,
        ["sha256"] = ScenarioReplay.Sha256(PyJson.Dumps(rows)),
        ["head"] = rows.Take(25).ToList(),
    };
}
