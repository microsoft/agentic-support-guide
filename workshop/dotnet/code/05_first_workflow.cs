#!/usr/bin/env dotnet
// Sample 5 — a workflow is executors joined by edges.
//
//     dotnet run workshop/dotnet/code/05_first_workflow.cs
//
// Mirrors https://learn.microsoft.com/agent-framework/get-started/workflows
//
// No model, no Azure, no network. Run this one offline.
//
// Three pieces, and that is the entire model:
//
//     EXECUTOR   a step. Either a class deriving from Executor, or a plain
//                function bound with BindAsExecutor.
//     EDGE       source -> target. The target runs when the source sends it
//                a message.
//     WORKFLOW   new WorkflowBuilder(start).AddEdge(...).Build()
//
// Inside an executor you use the IWorkflowContext to do either or both of:
//
//     context.SendMessageAsync(x)   pass x along the outgoing edges
//     context.YieldOutputAsync(x)   publish x as one of the workflow's results
//
// A handler's return value is sent along the outgoing edges for you, so the
// three steps here only return. Which steps' results count as the workflow's
// outputs is decided once, on the builder: WithOutputFrom(summarise). It is a
// statement about results, not a stop instruction: a step named there that
// also has outgoing edges still has its successors run.
//
// The payoff is the last few lines: because the workflow is data rather than
// control flow, WorkflowVisualizer can draw it. You cannot draw an if-statement.

#:include _shared.cs
#:package Microsoft.Agents.AI.Workflows

using Microsoft.Agents.AI.Workflows;

// The tests and the diagram renderer include this file too, and call
// BuildWorkflow() themselves. This part runs only when you run the file.
#if !INCLUDED
var workflow = FirstWorkflow.BuildWorkflow();

Workshop.Banner("Sample 5 — run it");
var outputs = await FirstWorkflow.RunAsync(workflow, "  Our first REPLY to an online enquiry is   slow ");
Console.WriteLine(outputs[0]);

Workshop.Banner("Sample 5 — draw it");
// Paste this into any Markdown file that renders Mermaid.
Console.WriteLine(workflow.ToMermaidString());
#endif

public static class FirstWorkflow
{
    /// <summary>A class-based executor. It handles one input type, and returns what it sends on.</summary>
    public sealed class Normalise() : Executor<string, string>("normalise")
    {
        public override ValueTask<string> HandleAsync(string concern, IWorkflowContext context, CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(string.Join(' ', concern.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)).ToLowerInvariant());
    }

    /// <summary>A function-based executor. Same thing, less ceremony.</summary>
    public static string Classify(string concern)
    {
        var area = concern.Contains("reply", StringComparison.Ordinal) || concern.Contains("enquiry", StringComparison.Ordinal) ? "lead-response" : "general";
        return $"{area}: {concern}";
    }

    /// <summary>Last step: what it returns is the workflow's output, because the builder says so.</summary>
    public static string Summarise(string tagged) => $"routed -> {tagged}";

    public static Workflow BuildWorkflow()
    {
        var normalise = new Normalise();
        var classify = ((Func<string, string>)Classify).BindAsExecutor("classify");
        var summarise = ((Func<string, string>)Summarise).BindAsExecutor("summarise");
        return new WorkflowBuilder(normalise)
            .WithName("triage")
            .AddEdge(normalise, classify)
            .AddEdge(classify, summarise)
            .WithOutputFrom(summarise)
            .Build();
    }

    /// <summary>Run the workflow once and return its outputs.</summary>
    public static async Task<List<string>> RunAsync(Workflow workflow, string concern)
    {
        await using var run = await InProcessExecution.RunAsync(workflow, concern);
        return [.. run.NewEvents.OfType<WorkflowOutputEvent>().Select(output => output.Data?.ToString() ?? "")];
    }
}
