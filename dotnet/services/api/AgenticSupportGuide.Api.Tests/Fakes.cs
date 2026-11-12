using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Test doubles for the Agent Framework runtime.
/// </summary>
/// <remarks>
/// Nothing here talks to Azure. The fake stands in for the client factory the
/// runtime calls, so tests exercise the real <see cref="MafAgentRuntime"/> -
/// including its error mapping and role resolution - without a network.
/// </remarks>
public sealed class FakeChatClientFactory
{
    public const string DefaultEndpoint = "https://fake-foundry.example.invalid/api/projects/asg";
    public const string DefaultDeployment = "fake-deployment";

    private readonly Dictionary<string, Queue<object>> _queues = [];
    private readonly List<FakeCall> _calls = [];
    private readonly Lock _lock = new();

    /// <summary>One recorded call, as the production factory would have made it.</summary>
    public sealed record FakeCall(
        string Role,
        string Model,
        string Instructions,
        string UserMessage,
        Type? ResponseModel,
        bool Store,
        double? Temperature,
        int? MaxOutputTokens);

    /// <summary>Queue a reply: a string is returned as-is, anything else as Python's <c>json.dumps</c> of it.</summary>
    public void RegisterResponse(string role, object payload) =>
        Enqueue(role, payload as string ?? (payload is System.Text.Json.JsonElement element ? PyJson.Dumps(element) : PyJson.Dumps(payload)));

    public void RegisterError(string role, Exception exception) => Enqueue(role, exception);

    public IReadOnlyList<FakeCall> Calls()
    {
        lock (_lock)
        {
            return [.. _calls];
        }
    }

    public Task<ChatResult> InvokeAsync(RoleDefinition definition, string userMessage, Type? responseModel, CancellationToken cancellationToken)
    {
        object item;
        lock (_lock)
        {
            // Mirrors the production factory, which always disables server-side
            // storage. Tests assert on this.
            _calls.Add(new FakeCall(
                definition.Role,
                definition.ModelDeployment,
                definition.Instructions,
                userMessage,
                responseModel,
                Store: false,
                definition.Temperature,
                definition.MaxOutputTokens));
            if (!_queues.TryGetValue(definition.Role, out var queue) || queue.Count == 0)
            {
                throw new InvalidOperationException($"no fake response queued for role '{definition.Role}'");
            }
            item = queue.Dequeue();
        }
        if (item is Exception exception)
        {
            throw exception;
        }
        return Task.FromResult(new ChatResult((string)item));
    }

    public static IReadOnlyDictionary<string, RoleDefinition> BuildRoleDefinitions(string instructions = "test instructions", double? temperature = 0.2) =>
        RoleDefinitions.RequiredRoles.ToDictionary(
            role => role,
            role => new RoleDefinition(role, instructions, DefaultDeployment, temperature));

    public static (MafAgentRuntime Runtime, FakeChatClientFactory Factory) MakeFakeRuntime(
        FakeChatClientFactory? factory = null,
        IReadOnlyDictionary<string, RoleDefinition>? roles = null)
    {
        factory ??= new FakeChatClientFactory();
        return (new MafAgentRuntime(roles ?? BuildRoleDefinitions(), factory.InvokeAsync), factory);
    }

    private void Enqueue(string role, object item)
    {
        lock (_lock)
        {
            if (!_queues.TryGetValue(role, out var queue))
            {
                _queues[role] = queue = new Queue<object>();
            }
            queue.Enqueue(item);
        }
    }
}
