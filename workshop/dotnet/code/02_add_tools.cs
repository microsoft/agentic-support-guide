#!/usr/bin/env dotnet
// Sample 2 — a tool is a C# method the model may call.
//
//     dotnet run workshop/dotnet/code/02_add_tools.cs
//
// Mirrors https://learn.microsoft.com/agent-framework/get-started/add-tools
//
// Sample 1 could only talk about what it already knew. A tool lets the model
// reach for a fact. You hand ordinary C# methods to `AIFunctionFactory.Create`;
// the parameter types and the `[Description]` attributes become the schema the
// model sees, so the attributes are not decoration.
//
// The model decides whether to call a tool. Watch what happens when you ask it
// something the tool cannot answer -- it should say so rather than invent a
// number. That choice is the model's, which is exactly why later modules stop
// relying on it.
//
// `GetProcessScore` only reads, so it needs no gate. A tool that **writes or
// takes an action** -- books an appointment, changes a price, sends an email --
// should be wrapped in `new ApprovalRequiredAIFunction(...)`, which pauses the
// run for a human to approve the specific call before it happens.

#:include _shared.cs

using System.ComponentModel;
using Azure.AI.Projects;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

AIAgent agent = Workshop.Project().AsAIAgent(
    model: Workshop.Model(),
    instructions: "You explain dealership sales-process problems to a general manager. "
        + "Use the get_process_score tool for any question about a specific "
        + "dealership's numbers. Never state a score you did not retrieve.",
    name: "support-explainer",
    tools: [AIFunctionFactory.Create(DealerSystem.GetProcessScore, name: "get_process_score")]);

Workshop.Banner("Sample 2 — the tool is called");
var answered = await agent.RunAsync("How is DLR-0001 doing on lead response?");
Console.WriteLine(answered.Text);

Workshop.Banner("Sample 2 — no tool can answer this");
var refused = await agent.RunAsync("How is DLR-9999 doing on lead response?");
Console.WriteLine(refused.Text);

/// <summary>Stand-in for a real dealer management system.</summary>
static class DealerSystem
{
    private static readonly Dictionary<string, Dictionary<string, int>> Scores = new()
    {
        ["DLR-0001"] = new() { ["lead-response"] = 41, ["test-drive-conversion"] = 63 },
        ["DLR-0002"] = new() { ["lead-response"] = 78, ["test-drive-conversion"] = 71 },
    };

    [Description("Return this month's process score (0-100) for one dealership and area.")]
    public static string GetProcessScore(
        [Description("Dealership id, for example DLR-0001")] string dealershipId,
        [Description("One of: lead-response, test-drive-conversion")] string processArea)
    {
        if (!Scores.TryGetValue(dealershipId, out var scores))
        {
            return $"No such dealership: {dealershipId}";
        }
        if (!scores.TryGetValue(processArea, out var score))
        {
            return $"No score recorded for {processArea}";
        }
        return $"{dealershipId} {processArea}: {score}/100";
    }
}
