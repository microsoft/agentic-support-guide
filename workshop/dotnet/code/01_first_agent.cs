#!/usr/bin/env dotnet
// Sample 1 — an agent is a model plus instructions.
//
//     dotnet run workshop/dotnet/code/01_first_agent.cs
//
// Mirrors https://learn.microsoft.com/agent-framework/get-started/your-first-agent
//
// That is the whole idea. `AsAIAgent` wraps a model deployment and a system
// prompt, and `RunAsync` sends one message. Everything else in this workshop
// is added on top of these six lines.

#:include _shared.cs

using Azure.AI.Projects;
using Microsoft.Agents.AI;

const string Instructions = """

    You explain dealership sales-process problems to a general manager.
    Answer in at most three sentences. Plain language, no jargon.

    """;

AIAgent agent = Workshop.Project().AsAIAgent(
    model: Workshop.Model(),
    instructions: Instructions,
    name: "support-explainer");

Workshop.Banner("Sample 1 — first agent");
var response = await agent.RunAsync(
    "Our median first reply to an online enquiry has slipped past one hour. "
    + "Why does that matter?");
Console.WriteLine(response.Text);
