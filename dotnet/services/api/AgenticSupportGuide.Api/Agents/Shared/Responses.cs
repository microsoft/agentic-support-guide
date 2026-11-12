using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Agents.Shared;

/// <summary>
/// Read a role response as a validated contract.
/// </summary>
/// <remarks>
/// The structured-output response format asks the provider for JSON matching
/// the contract's schema. Not every model deployment supports strict
/// structured output, so the text is always validated here rather than
/// trusted, and a learner whose deployment lacks the feature gets the same
/// checks.
/// </remarks>
public static class Responses
{
    /// <summary>Return the response as a contract, or throw <see cref="ModelOutputException"/> with a stable reason.</summary>
    public static T ParseRoleResponse<T>(RoleResponse response, Func<PydanticReader, T?> parse)
        where T : class =>
        Contracts.ParseModelOutput(response.Text, parse);
}
