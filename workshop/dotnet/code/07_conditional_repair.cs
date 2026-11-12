#!/usr/bin/env dotnet
// Sample 7 — a conditional edge can send work back.
//
//     dotnet run workshop/dotnet/code/07_conditional_repair.cs
//
// Mirrors the conditional-edge half of
// https://learn.microsoft.com/agent-framework/concepts/workflows/
//
// **This is the shape the whole application uses.** Module 3 picks it up.
//
// Sample 6 was a straight line. Real work is not: sometimes a step produces
// something that is not good enough, and you want one more try rather than a
// failure. That is a condition on `AddEdge`:
//
//     .AddEdge<Draft>(source, target, condition: draft => ...)
//
// The edge is only followed when the condition returns true. Two conditions
// out of the same node are a branch. A condition on an edge pointing *back*
// is a bounded loop.
//
// Here the validator either accepts a draft, or sends it back once with a
// reason attached:
//
//     retrieve -> recommend -> validate -+-> accept        (passed)
//                     ^                  |
//                     +------------------+                (failed, 1st time)
//                                        |
//                                        +-> give_up      (failed twice)
//
// Four rules worth copying:
//
// - **Messages are values, never mutated.** `Draft` is a record and every step
//   returns a new one with `with`. Several outgoing edges are handed the same
//   message and evaluate their conditions independently; a step that changes
//   a message it was handed changes it for everyone holding it. A record
//   cannot be changed in place, so that mistake cannot be written here.
// - **The validator is plain C#.** It is a set-membership test over ids the
//   retriever produced. A second model asked "is this well cited?" would be an
//   opinion; `Contains` is an answer.
// - **The loop is bounded by data, not by hope.** `Draft.Attempts` travels in
//   the message, and the repair condition checks it. Nothing else stops it:
//   Agent Framework for .NET keeps running a cycle for as long as its
//   conditions keep firing, so a condition that never turns false is an
//   endless loop.
// - **Failing twice does not produce output.** `GiveUp` yields a refusal, not
//   a recommendation. A workflow that returns something plausible when it
//   could not do the job is worse than one that returns nothing.
//
// No model and no network, so this runs offline. The stub recommender decides
// what to do from a tag in the concern text rather than at random, so one run
// walks all three paths and you can see each of them every time.

#:include _shared.cs
#:package Microsoft.Agents.AI.Workflows

using Microsoft.Agents.AI.Workflows;

// The tests and the diagram renderer include this file too, and call
// BuildWorkflow() themselves. This part runs only when you run the file.
#if !INCLUDED
var workflow = ConditionalRepair.BuildWorkflow();

Workshop.Banner("Sample 7 — draw it");
Console.WriteLine(workflow.ToMermaidString());
Console.WriteLine(
    "\nThe renderer labels every conditional edge 'conditional'. Which\n"
    + "condition is which is in BuildWorkflow(): Passed, NeedsRepair,\n"
    + "Exhausted. A diagram shows you the shape, not the rules.");

Workshop.Banner("Sample 7 — all three paths");
foreach (var (label, tag) in new[]
{
    ("accepted first time", ConditionalRepair.NeverInvents),
    ("repaired, then accepted", ConditionalRepair.InventsOnce),
    ("repair exhausted", ConditionalRepair.AlwaysInvents),
})
{
    var outputs = await ConditionalRepair.RunAsync(workflow, $"{tag} First reply to online enquiries is slow.");
    // Exactly one, always. Two would mean a condition fired that should not.
    var result = outputs.Count == 1 ? outputs[0] : $"BUG: {outputs.Count} outputs {ConditionalRepair.PyList(outputs)}";
    Console.WriteLine($"  {label,-24} -> {result}");
}
#endif

public static class ConditionalRepair
{
    public static readonly IReadOnlyList<string> AllowedCitations = ["EV-101", "EV-102", "EV-103"];
    public const int MaxAttempts = 2;

    // Which attempts the stub recommender invents a citation on. Stands in for
    // a model that sometimes gets it wrong, without the randomness that would
    // make this file behave differently every run.
    public const string NeverInvents = "[clean]";
    public const string InventsOnce = "[repairable]";
    public const string AlwaysInvents = "[unfixable]";

    /// <summary>What travels along the edges. A record, so no step can surprise another.</summary>
    public sealed record Draft(string Concern)
    {
        public IReadOnlyList<string> Allowed { get; init; } = [];
        public string Text { get; init; } = "";
        public IReadOnlyList<string> Cited { get; init; } = [];
        public int Attempts { get; init; }
        public string RepairReason { get; init; } = "";
        public IReadOnlyList<string> Issues { get; init; } = [];
    }

    /// <summary>Stands in for a model's unreliability, made reproducible.</summary>
    public static bool InventsOn(string concern, int attempt)
    {
        if (concern.Contains(AlwaysInvents, StringComparison.Ordinal))
        {
            return true;
        }
        if (concern.Contains(InventsOnce, StringComparison.Ordinal))
        {
            return attempt == 1;
        }
        return false;
    }

    /// <summary>Grounding happens first, in code. Sample 4 is this step in full.</summary>
    public static Draft Retrieve(string concern) => new(concern) { Allowed = AllowedCitations };

    /// <summary>Stands in for an agent. Sample 6 shows the real thing.</summary>
    public static Draft Recommend(Draft draft)
    {
        var attempts = draft.Attempts + 1;
        var invented = InventsOn(draft.Concern, attempts);
        return draft with
        {
            Attempts = attempts,
            // An id the retriever never returned: exactly the failure a real
            // model makes.
            Cited = invented ? ["EV-999"] : ["EV-101", "EV-102"],
            Text = "Assign a named advisor to every online enquiry.",
        };
    }

    /// <summary>Deterministic checks. No model, no opinion.</summary>
    public static Draft Validate(Draft draft)
    {
        var allowed = draft.Allowed.ToHashSet();
        List<string> issues = [.. draft.Cited.Where(cited => !allowed.Contains(cited))];
        return draft with
        {
            Issues = issues,
            RepairReason = issues.Count > 0 ? $"Cite only {string.Join(", ", draft.Allowed)}." : "",
        };
    }

    public static string Accept(Draft draft) =>
        $"OK after {draft.Attempts} attempt(s): {draft.Text} {PyList(draft.Cited)}";

    /// <summary>No recommendation. A typed refusal is the honest answer.</summary>
    public static string GiveUp(Draft draft) =>
        $"REFUSED after {draft.Attempts} attempt(s): unknown citations {PyList(draft.Issues)}";

    public static bool Passed(Draft? draft) => draft is { Issues.Count: 0 };

    public static bool NeedsRepair(Draft? draft) => draft is { Issues.Count: > 0 } && draft.Attempts < MaxAttempts;

    public static bool Exhausted(Draft? draft) => draft is { Issues.Count: > 0 } && draft.Attempts >= MaxAttempts;

    /// <summary>The whole workflow. Every rule is one line of it.</summary>
    public static Workflow BuildWorkflow()
    {
        var retrieve = ((Func<string, Draft>)Retrieve).BindAsExecutor("retrieve");
        var recommend = ((Func<Draft, Draft>)Recommend).BindAsExecutor("recommend");
        var validate = ((Func<Draft, Draft>)Validate).BindAsExecutor("validate");
        var accept = ((Func<Draft, string>)Accept).BindAsExecutor("accept");
        var giveUp = ((Func<Draft, string>)GiveUp).BindAsExecutor("give_up");
        return new WorkflowBuilder(retrieve)
            .WithName("support-plan")
            .AddEdge(retrieve, recommend)
            .AddEdge(recommend, validate)
            .AddEdge<Draft>(validate, accept, condition: Passed)
            .AddEdge<Draft>(validate, recommend, condition: NeedsRepair)
            .AddEdge<Draft>(validate, giveUp, condition: Exhausted)
            .WithOutputFrom(accept, giveUp)
            .Build();
    }

    /// <summary>Run the workflow once and return its outputs.</summary>
    public static async Task<List<string>> RunAsync(Workflow workflow, string concern)
    {
        await using var run = await InProcessExecution.RunAsync(workflow, concern);
        return [.. run.NewEvents.OfType<WorkflowOutputEvent>().Select(output => output.Data?.ToString() ?? "")];
    }

    /// <summary>A list as Python prints one, so both tracks print the same lines.</summary>
    public static string PyList(IEnumerable<string> items) => "[" + string.Join(", ", items.Select(item => $"'{item}'")) + "]";
}
