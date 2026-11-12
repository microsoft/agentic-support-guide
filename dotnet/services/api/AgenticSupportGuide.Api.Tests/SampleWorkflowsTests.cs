using Microsoft.Agents.AI.Workflows;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>The workshop samples are taught as correct, so they are tested as correct.</summary>
/// <remarks>
/// Three kinds of check:
///
/// - behaviour: each conditional edge routes to the right terminal executor,
///   and exactly one of them ever fires;
/// - the rule sample 7 teaches: a mutable message really does make a stale
///   condition fire, and the record version really does not;
/// - drift: the Mermaid committed in the workshop still matches what
///   <c>WorkflowVisualizer</c> renders from the code.
///
/// The drift check alone is not enough. A condition can change while the
/// rendered diagram stays byte-identical, because the renderer labels every
/// conditional edge "conditional".
/// </remarks>
public class SampleWorkflowsTests
{
    private static Task<List<string>> RunAsync(string tag) =>
        ConditionalRepair.RunAsync(ConditionalRepair.BuildWorkflow(), $"{tag} first reply is slow");

    [Fact]
    public async Task First_workflow_runs_offline()
    {
        var outputs = await FirstWorkflow.RunAsync(FirstWorkflow.BuildWorkflow(), "  Our first REPLY is   slow ");
        Assert.Equal(["routed -> lead-response: our first reply is slow"], outputs);
    }

    [Fact]
    public async Task Clean_draft_is_accepted_on_the_first_attempt()
    {
        var outputs = await RunAsync(ConditionalRepair.NeverInvents);
        Assert.Single(outputs);
        Assert.StartsWith("OK after 1 attempt(s)", outputs[0], StringComparison.Ordinal);
    }

    [Fact]
    public async Task Bad_citation_is_repaired_and_then_accepted()
    {
        var outputs = await RunAsync(ConditionalRepair.InventsOnce);
        Assert.Single(outputs);
        Assert.StartsWith("OK after 2 attempt(s)", outputs[0], StringComparison.Ordinal);
        Assert.DoesNotContain("EV-999", outputs[0], StringComparison.Ordinal);
    }

    [Fact]
    public async Task Exhausted_repair_refuses_and_returns_no_recommendation()
    {
        // The branch the sample claims to teach has to be reachable.
        var outputs = await RunAsync(ConditionalRepair.AlwaysInvents);
        Assert.Single(outputs);
        Assert.StartsWith($"REFUSED after {ConditionalRepair.MaxAttempts} attempt(s)", outputs[0], StringComparison.Ordinal);
        Assert.DoesNotContain("Assign a named advisor", outputs[0], StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(ConditionalRepair.NeverInvents)]
    [InlineData(ConditionalRepair.InventsOnce)]
    [InlineData(ConditionalRepair.AlwaysInvents)]
    public async Task Exactly_one_terminal_executor_fires_per_run(string tag)
    {
        Assert.Single(await RunAsync(tag));
    }

    // --- the rule sample 7 teaches ------------------------------------------
    //
    // Outgoing edges are handed the same message object and evaluate their
    // conditions independently. This workflow is sample 7's shape with a
    // mutable message, so the documented bug is reproduced rather than asserted.

    /// <summary>Sample 7's Draft, as a mutable class instead of a record.</summary>
    private sealed class Mutable
    {
        public List<string> Allowed { get; } = ["EV-101"];
        public List<string> Cited { get; set; } = [];
        public int Attempts { get; set; }
        public List<string> Issues { get; set; } = [];
    }

    private static Workflow MutableWorkflow()
    {
        var recommend = ((Func<Mutable, Mutable>)(draft =>
        {
            draft.Attempts++;
            // Note what this does NOT touch: Issues. Only the validator sets
            // those, which is why a stale edge can still be holding the old ones.
            draft.Cited = draft.Attempts == 1 ? ["EV-999"] : ["EV-101"];
            return draft;
        })).BindAsExecutor("m_recommend");
        var validate = ((Func<Mutable, Mutable>)(draft =>
        {
            draft.Issues = [.. draft.Cited.Where(cited => !draft.Allowed.Contains(cited))];
            return draft;
        })).BindAsExecutor("m_validate");
        var accept = ((Func<Mutable, string>)(_ => "accepted")).BindAsExecutor("m_accept");
        var giveUp = ((Func<Mutable, string>)(_ => "refused")).BindAsExecutor("m_give_up");
        return new WorkflowBuilder(recommend)
            .WithName("mutable")
            .AddEdge(recommend, validate)
            .AddEdge<Mutable>(validate, accept, condition: d => d is { Issues.Count: 0 })
            .AddEdge<Mutable>(validate, recommend, condition: d => d is { Issues.Count: > 0, Attempts: < 2 })
            .AddEdge<Mutable>(validate, giveUp, condition: d => d is { Issues.Count: > 0, Attempts: >= 2 })
            .WithOutputFrom(accept, giveUp)
            .Build();
    }

    [Fact]
    public async Task A_mutated_message_does_not_make_a_stale_condition_fire()
    {
        // Sample 7's shape with a mutable message. In Python's Agent Framework
        // the repair round's change to the object makes the exhausted edge fire
        // as well, and one run yields two answers. In the .NET framework the
        // same change does not make a second edge fire, so the run yields one
        // (conformance/allowed_differences.yaml, mutated-workflow-message). If
        // this ever yields two, the framework changed and sample 7's lesson
        // needs rewriting.
        await using var run = await InProcessExecution.RunAsync(MutableWorkflow(), new Mutable(), cancellationToken: TestContext.Current.CancellationToken);
        var outputs = run.NewEvents.OfType<WorkflowOutputEvent>().Select(output => output.Data?.ToString() ?? "").ToList();

        Assert.Equal(["accepted"], outputs);
    }

    [Fact]
    public async Task The_frozen_version_of_the_same_flow_yields_one_answer()
    {
        // The fix sample 7 prescribes, over the same repair path.
        Assert.Single(await RunAsync(ConditionalRepair.InventsOnce));
    }

    public static TheoryData<string, string, string> Diagrams() =>
        [.. RenderWorkflowDiagram.Diagrams.Select(d => (d.Key, d.Marker, d.Path))];

    [Theory]
    [MemberData(nameof(Diagrams))]
    public void Committed_diagram_matches_the_built_workflow(string key, string marker, string path)
    {
        var expected = RenderWorkflowDiagram.Render(key);
        var actual = RenderWorkflowDiagram.Committed(path, marker);
        Assert.True(actual is not null, $"{Path.GetFileName(path)} has no <!-- {marker}:start --> block");
        Assert.True(
            actual == expected,
            $"{Path.GetFileName(path)} is stale. Regenerate with:\n  dotnet run dotnet/scripts/render_workflow_diagram.cs -- --write");
    }
}
