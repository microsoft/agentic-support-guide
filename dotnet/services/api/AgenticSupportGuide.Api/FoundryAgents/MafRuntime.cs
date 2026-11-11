namespace AgenticSupportGuide.Api.FoundryAgents;

/// <summary>What one role call returned.</summary>
/// <param name="Model">
/// Deployment that served the call. Differs from the requested deployment
/// when a model router is in front.
/// </param>
public sealed record RoleResponse(string Role, string Text, string Model = "", int? InputTokens = null, int? OutputTokens = null)
{
    public int? TotalTokens => InputTokens is null && OutputTokens is null ? null : (InputTokens ?? 0) + (OutputTokens ?? 0);
}

/// <summary>One agent role: its composed instructions and model settings.</summary>
public sealed record RoleDefinition(
    string Role,
    string Instructions,
    string ModelDeployment,
    double? Temperature,
    int? MaxOutputTokens = null);

/// <summary>What a client factory returns for one call.</summary>
/// <param name="Model">
/// The deployment that actually served the call. With a model router this
/// differs from the deployment name that was requested.
/// </param>
public sealed record ChatResult(string Text, string Model = "", int? InputTokens = null, int? OutputTokens = null);

/// <summary>
/// Runs one role call. The production factory is <see cref="FoundryResponsesClientFactory"/>;
/// tests substitute a fake.
/// </summary>
public delegate Task<ChatResult> RoleClientFactory(
    RoleDefinition definition,
    string userMessage,
    Type? responseModel,
    CancellationToken cancellationToken);

/// <summary>
/// Microsoft Agent Framework runtime for the three agent roles.
/// </summary>
/// <remarks>
/// Each role is an Agent Framework agent backed by the Foundry project's
/// Responses API. This is the local development inner loop: instructions are
/// composed from <c>/agents/&lt;id&gt;/agent.md</c> once at application
/// construction and cached here, so a prompt edit takes effect on the next
/// process start with no publish step.
///
/// Publishing the same definitions to Foundry as prompt agents is a separate
/// GenAIOps step - see <c>dotnet/scripts/publish_prompt_agents.cs</c>.
/// </remarks>
public sealed class MafAgentRuntime(IReadOnlyDictionary<string, RoleDefinition> roles, RoleClientFactory clientFactory)
{
    // Value recorded on traces and audit rows. Single source of truth; a drift
    // test asserts nothing else hardcodes it.
    public const string ProviderId = "azure_foundry_responses";

    public IReadOnlyDictionary<string, RoleDefinition> Roles => roles;

    public bool HasRole(string role) => roles.ContainsKey(role);

    public bool AllRolesAvailable(IEnumerable<string> required) => required.All(HasRole);

    public async Task<RoleResponse> InvokeAsync(string role, string userMessage, Type? responseModel = null, CancellationToken cancellationToken = default)
    {
        if (!roles.TryGetValue(role, out var definition))
        {
            throw new ConfigurationException("ROLE_NOT_CONFIGURED", $"Role '{role}' has no model deployment configured.");
        }

        ChatResult result;
        try
        {
            // No session/conversation id: every role call is isolated so prior
            // agent output can never leak in as conversation history.
            result = await clientFactory(definition, userMessage, responseModel, cancellationToken);
        }
        catch (FoundryProviderException)
        {
            throw;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Shutdown/cancellation must propagate, not become a provider error.
            throw;
        }
        catch (Exception exc)
        {
            throw ErrorMapping.MapProviderError(exc);
        }

        return new RoleResponse(
            Role: role,
            Text: result.Text,
            Model: string.IsNullOrEmpty(result.Model) ? definition.ModelDeployment : result.Model,
            InputTokens: result.InputTokens,
            OutputTokens: result.OutputTokens);
    }
}
