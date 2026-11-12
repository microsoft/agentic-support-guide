#!/usr/bin/env dotnet
// Sample 3 — a session carries conversation history.
//
//     dotnet run workshop/dotnet/code/03_multi_turn.cs
//
// Mirrors https://learn.microsoft.com/agent-framework/get-started/multi-turn
//
// `agent.RunAsync(...)` with no session is stateless: every call starts from
// nothing. Pass the same session twice and the second call can see the first.
//
// This sample does both, so you can watch "it" resolve in one case and fail in
// the other. Session state is also the reason a real service cannot share one
// conversation between two users -- each caller needs their own.

#:include _shared.cs

using Azure.AI.Projects;
using Microsoft.Agents.AI;

const string FollowUp = "Which of those would you do first?";

AIAgent agent = Workshop.Project().AsAIAgent(
    model: Workshop.Model(),
    instructions: "You explain dealership sales-process problems to a general manager. "
        + "Answer in at most three sentences.",
    name: "support-explainer");

Workshop.Banner("Sample 3 — no session, so the follow-up has no referent");
await agent.RunAsync("Name two causes of slow first reply to online enquiries.");
var stateless = await agent.RunAsync(FollowUp);
Console.WriteLine(stateless.Text);

Workshop.Banner("Sample 3 — same session, so the follow-up resolves");
var session = await agent.CreateSessionAsync();
await agent.RunAsync("Name two causes of slow first reply to online enquiries.", session);
var stateful = await agent.RunAsync(FollowUp, session);
Console.WriteLine(stateful.Text);
