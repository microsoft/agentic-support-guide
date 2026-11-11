#!/usr/bin/env dotnet
// Sample 6 — agents can be steps in a workflow.
//
//     dotnet run workshop/dotnet/code/06_agents_in_a_workflow.cs
//
// Mirrors https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
//
// Sample 5's executors were plain C#. Swap two of them for agents and you
// have **sequential orchestration**: agents in a fixed order, each working on
// what the one before it produced.
//
// An agent can be passed straight to `AddEdge`; Agent Framework hosts it as
// an executor that collects the messages it is sent, runs the agent when a
// `TurnToken` arrives, and sends the agent's reply to the next step.
//
// Three details that bite:
//
// - **An agent's response is not the workflow's answer.** An agent can
//   publish its whole response as an event (`EmitAgentResponseEvents`). Turn
//   that on and every agent in the graph does it, so the outputs would hold
//   two responses and `[0]` would be the *analyst*, not the answer. Here it
//   stays off, and `WithOutputFrom(finalise)` names the one step whose result
//   is the workflow's answer.
// - **By default an agent forwards what it was given.** The recommender
//   receives the original dealership record as well as the analyst's
//   finding, because the analyst's executor forwards its input along with
//   its reply (`ForwardIncomingMessages`). If you want a step to see only
//   what the previous step said -- which is often the point of splitting them
//   up -- you have to say so explicitly, as the recommender does here so that
//   `finalise` sees only the recommendation. This sample keeps the analyst's
//   default and tells you, rather than claiming an isolation it does not have.
// - **A reply stays the assistant's.** By default the next agent receives
//   another agent's reply relabelled as the user's
//   (`ReassignOtherAgentsAsUsers`). The Foundry Responses API rejects that
//   relabelled reply, so both agents here keep it as written.
//
// Agent Framework also ships `AgentWorkflowBuilder.BuildSequential` for a pure
// agent pipeline like this one. It builds a straight line. Sample 7 needs an
// edge that goes backwards, which a straight line cannot express -- so this
// workshop uses `WorkflowBuilder` throughout and you only learn one API.

#:include _shared.cs
#:package Microsoft.Agents.AI.Workflows

using Azure.AI.Projects;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Workflows;
using Microsoft.Extensions.AI;

const string Dealership =
    "DLR-0001, volume segment. lead-response 41/100 and falling for three months. "
    + "test-drive-conversion 63/100 and flat. Appointments attended 72%.";

var workflow = AgentsInAWorkflow.BuildWorkflow(Workshop.Project(), Workshop.Model());

Workshop.Banner("Sample 6 — draw it first");
Console.WriteLine(workflow.ToMermaidString());

Workshop.Banner("Sample 6 — then run it");
await using var run = await InProcessExecution.RunStreamingAsync(workflow, new ChatMessage(ChatRole.User, Dealership));
// The agents hold what they are sent until a turn token tells them to run.
await run.TrySendMessageAsync(new TurnToken());
List<string> outputs = [];
await foreach (var evt in run.WatchStreamAsync())
{
    if (evt is WorkflowOutputEvent output)
    {
        outputs.Add(output.Data?.ToString() ?? "");
    }
}
Console.WriteLine($"{outputs.Count} output(s)");
Console.WriteLine(outputs[0]);

static class AgentsInAWorkflow
{
    public static Workflow BuildWorkflow(AIProjectClient project, string model)
    {
        var analyst = new AIAgentBinding(
            Agent(project, model, "analyst",
                "You read dealership process scores. State the single most important "
                + "finding and the evidence for it, in two sentences. Recommend nothing."),
            new AIAgentHostOptions { ReassignOtherAgentsAsUsers = false });
        var recommender = new AIAgentBinding(
            Agent(project, model, "recommender",
                "You turn a finding into one concrete action a general manager can "
                + "take this week. Two sentences. Do not restate the finding."),
            new AIAgentHostOptions { ReassignOtherAgentsAsUsers = false, ForwardIncomingMessages = false });

        // The recommender sends its reply on as messages; the answer is the last one.
        var finalise = ((Func<List<ChatMessage>, string>)(reply => reply[^1].Text)).BindAsExecutor("finalise");

        return new WorkflowBuilder(analyst)
            .WithName("support-plan")
            .AddEdge(analyst, recommender)
            .AddEdge(recommender, finalise)
            // Without this, the workflow has no answer at all: nothing else is named.
            .WithOutputFrom(finalise)
            .Build();
    }

    // The id names the step in the workflow and in the diagram. A name as
    // well would make it "analyst_analyst": the executor id is name_id.
    private static AIAgent Agent(AIProjectClient project, string model, string id, string instructions) =>
        project.AsAIAgent(new ChatClientAgentOptions
        {
            Id = id,
            ChatOptions = new ChatOptions { ModelId = model, Instructions = instructions },
        });
}
