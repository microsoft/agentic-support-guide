using AgenticSupportGuide.Api.Parity;
using Azure.AI.Projects;
using Azure.Core;
using Azure.Identity;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using OpenAI.Responses;

namespace AgenticSupportGuide.Api.FoundryAgents;

/// <summary>
/// Builds and invokes an Agent Framework agent per call. The only type that
/// uses the Agent Framework model-client API.
/// </summary>
/// <remarks>
/// Keeping it here means the rest of the app depends on <see cref="MafAgentRuntime"/>,
/// and a drift test can assert that persisted-agent APIs are never used
/// anywhere.
///
/// Storage is disabled on every call: the OpenAI Responses client used under
/// the hood stores by default, and this prototype must not leave response
/// bodies server-side.
/// </remarks>
public sealed class FoundryResponsesClientFactory
{
    private readonly AIProjectClient _project;
    private readonly ILoggerFactory? _loggerFactory;

    public FoundryResponsesClientFactory(string projectEndpoint, TokenCredential? credential = null, AIProjectClientOptions? options = null, ILoggerFactory? loggerFactory = null)
    {
        if (string.IsNullOrEmpty(projectEndpoint))
        {
            throw new ConfigurationException("PROJECT_ENDPOINT_MISSING", "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.");
        }
        _project = new AIProjectClient(new Uri(projectEndpoint), credential ?? new DefaultAzureCredential(), options ?? new AIProjectClientOptions());
        _loggerFactory = loggerFactory;
    }

    public async Task<ChatResult> InvokeAsync(RoleDefinition definition, string userMessage, Type? responseModel, CancellationToken cancellationToken)
    {
        var textOptions = responseModel is null ? null : ResponseTextOptionsFor(definition, responseModel);
        var chatOptions = new ChatOptions
        {
            Temperature = definition.Temperature is { } t ? (float)t : null,
            MaxOutputTokens = definition.MaxOutputTokens,
            RawRepresentationFactory = _ => new CreateResponseOptions { StoredOutputEnabled = false, TextOptions = textOptions },
        };

        // Agent Framework's own instrumentation on both layers: `invoke_agent`
        // for the agent and `chat <deployment>` for the model call.
        AIAgent agent = _project
            .AsAIAgent(
                model: definition.ModelDeployment,
                instructions: definition.Instructions,
                name: definition.Role,
                clientFactory: client => client.AsBuilder().UseOpenTelemetry(_loggerFactory, Observability.SourceName).Build(),
                loggerFactory: _loggerFactory)
            .AsBuilder()
            .UseOpenTelemetry(Observability.SourceName)
            .Build();

        // No session: every role call is isolated, so prior agent output can
        // never leak in as conversation history.
        var response = await agent.RunAsync(userMessage, session: null, options: new ChatClientAgentRunOptions(chatOptions), cancellationToken: cancellationToken);

        var text = response.Text ?? "";
        if (text.Length == 0)
        {
            throw new FoundryRunException("EMPTY_RESPONSE", "Remote agent returned no content.");
        }
        return new ChatResult(
            Text: text,
            Model: ServedModel(response) is { Length: > 0 } served ? served : definition.ModelDeployment,
            InputTokens: response.Usage?.InputTokenCount is { } input ? (int)input : null,
            OutputTokens: response.Usage?.OutputTokenCount is { } output ? (int)output : null);
    }

    /// <summary>
    /// The reply's JSON schema, sent exactly as the agent folder declares it.
    /// </summary>
    /// <remarks>
    /// The schema is the agent folder's <c>output.schema.json</c>, which the
    /// Python track generates from its contracts and both tracks send, strict.
    /// Generating one from the C# types instead would ask the model for a
    /// slightly different shape. The reply is not parsed here: the agents
    /// validate it, so an off-contract reply is reported as
    /// <c>invalid_model_json</c> in both tracks.
    /// </remarks>
    private static ResponseTextOptions ResponseTextOptionsFor(RoleDefinition definition, Type responseModel)
    {
        if (definition.ResponseSchema is not { } schema)
        {
            throw new ConfigurationException("RESPONSE_SCHEMA_MISSING", $"Role '{definition.Role}' has no output schema in its agent folder.");
        }
        return new ResponseTextOptions
        {
            TextFormat = ResponseTextFormat.CreateJsonSchemaFormat(
                responseModel.Name,
                BinaryData.FromString(schema.GetRawText()),
                jsonSchemaFormatDescription: null,
                jsonSchemaIsStrict: true),
        };
    }

    /// <summary><see cref="AgentResponse"/> has no model field; the underlying <see cref="ChatResponse"/> does.</summary>
    private static string? ServedModel(AgentResponse response) => (response.RawRepresentation as ChatResponse)?.ModelId;
}
