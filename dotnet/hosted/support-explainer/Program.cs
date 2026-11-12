// Hosted agent: the Support Explainer, running as Foundry-managed code.
//
// Same role as the Module 4 prompt agent, same instructions file. The
// difference is where it runs and what it can do: this process is built and
// run by Foundry, gets its own Entra identity, and can carry any dependency
// in SupportExplainer.csproj.
//
// Agent Framework's Foundry hosting serves the agent over the Responses
// protocol; Foundry starts it with `dotnet SupportExplainer.dll`.
// AZURE_AI_FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL_DEPLOYMENT arrive as
// environment variables set at deploy time; the credential resolves to the
// agent's own identity, not yours.
//
// The input bounds and the output gate are SafetyGate, in SafetyGate.cs, so
// they can be tested without booting this server.

using AgenticSupportGuide.Hosted;
using Azure.AI.Projects;
using Azure.Identity;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Foundry.Hosting;
using Microsoft.Extensions.AI;
using OpenAI.Responses;

static string Required(string name) =>
    Environment.GetEnvironmentVariable(name) is { Length: > 0 } value
        ? value
        : throw new InvalidOperationException($"{name} is not set.");

var project = new AIProjectClient(new Uri(Required("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")), new DefaultAzureCredential());

AIAgent agent = SafetyGate.Around(project.AsAIAgent(new ChatClientAgentOptions
{
    Name = "support-explainer",
    ChatOptions = new ChatOptions
    {
        ModelId = Required("FOUNDRY_MODEL_DEPLOYMENT"),
        Instructions = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "instructions.md")),
        // The model service keeps nothing either.
        RawRepresentationFactory = _ => new CreateResponseOptions { StoredOutputEnabled = false },
    },
}));

var builder = WebApplication.CreateBuilder(args);
// Foundry health-checks and routes to this port.
builder.WebHost.UseUrls($"http://0.0.0.0:{Environment.GetEnvironmentVariable("PORT") ?? "8088"}");
// The host passes the agent this request's input and a session; SafetyGate
// drops the session, so no earlier turn reaches the model. Registered on the
// builder, not on builder.Services: in Foundry the host binds its storage
// identities from configuration, and refuses to start otherwise.
builder.AddFoundryResponses(agent);

var app = builder.Build();
app.MapFoundryResponses();
app.Run();
