namespace AgenticSupportGuide.Api.Tests;

/// <summary>Deleting agents must hit exactly what was named, and nothing else.</summary>
/// <remarks>
/// <c>--variant strict --delete</c> once deleted every agent for the suffix,
/// because the target set was seeded with the base names and the variant was
/// only ever added to it. Naming a variant explicitly made the blast radius
/// larger rather than smaller, which is the opposite of what the flag is for. A
/// learner tidying up one Module 8 variant lost the whole project.
///
/// These assert the target set directly. Nothing here touches Azure.
/// </remarks>
public class AgentDeleteScopingTests
{
    [Fact]
    public void Variant_delete_does_not_touch_base_agents()
    {
        var targets = PublishPromptAgents.DeleteTargets("demo", ["strict"]);
        var baseNames = PublishPromptAgents.DeleteTargets("demo", []);
        Assert.True(targets.Count > 0, "variant delete selected nothing");
        Assert.True(!targets.Overlaps(baseNames), $"variant delete would also remove base agents: {string.Join(", ", targets.Intersect(baseNames))}");
        Assert.All(targets, name => Assert.EndsWith("-strict", name, StringComparison.Ordinal));
    }

    [Fact]
    public void Plain_delete_does_not_touch_variants()
    {
        var baseNames = PublishPromptAgents.DeleteTargets("demo", []);
        Assert.All(baseNames, name => Assert.False(name.EndsWith("-strict", StringComparison.Ordinal) || name.EndsWith("-baseline", StringComparison.Ordinal)));
    }

    [Fact]
    public void Suffix_match_is_exact_not_prefix()
    {
        // Suffixes are single-dash, so `ann` must not select `ann-smith`'s agents.
        Assert.False(PublishPromptAgents.DeleteTargets("ann", []).Overlaps(PublishPromptAgents.DeleteTargets("ann-smith", [])));
    }
}
