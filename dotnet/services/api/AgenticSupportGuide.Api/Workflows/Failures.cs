using System.Text.Json;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;

namespace AgenticSupportGuide.Api.Workflows;

/// <summary>Provider and parse failures mapped to the API's status taxonomy.</summary>
public static class Failures
{
    // Bounded set. An issue code reaches the API response and telemetry, so it
    // must never be built from exception text. Codes match
    // ^[A-Z][A-Z0-9_]{3,59}$, so no colons or lowercase.
    private const string InvalidJsonSchema = "AGENT_INVALID_JSON_SCHEMA_MISMATCH";
    private const string InvalidJsonDecode = "AGENT_INVALID_JSON_NOT_JSON";
    private const string InvalidJsonOther = "AGENT_INVALID_JSON_UNPARSEABLE";

    private static readonly Dictionary<string, string> SafeMessages = new()
    {
        ["provider_timeout"] = "Remote agent run timed out.",
        ["provider_throttling"] = "Remote agent was throttled.",
        ["provider_content_filter"] = "Remote agent blocked the request via content safety.",
        ["provider_error"] = "Remote agent returned an error.",
        ["provider_missing"] = $"Foundry Agent Service is not configured or bindings are missing. Run {Track.ValidateAgentDefinitions}.",
    };

    /// <summary>Map a typed provider error to (status, issue code).</summary>
    public static (string Status, string Code) ClassifyProviderError(FoundryProviderException exc) => exc switch
    {
        ConfigurationException => ("provider_missing", "AGENT_PROVIDER_MISSING"),
        AuthException => ("provider_error", "AGENT_PROVIDER_AUTH_DENIED"),
        ThrottledException => ("provider_throttling", "AGENT_PROVIDER_THROTTLING"),
        ContentFilterException => ("provider_content_filter", "AGENT_PROVIDER_CONTENT_FILTER"),
        FoundryTimeoutException => ("provider_timeout", "AGENT_PROVIDER_TIMEOUT"),
        RequiresActionException => ("provider_error", "AGENT_PROVIDER_REQUIRES_ACTION"),
        FoundryRunException => ("provider_error", "AGENT_PROVIDER_ERROR"),
        _ => ("provider_error", "AGENT_PROVIDER_ERROR"),
    };

    public static string SafeMessage(string status) => SafeMessages.GetValueOrDefault(status, "Unknown remote agent error.");

    /// <summary>Classify a parse failure without echoing its message.</summary>
    public static string InvalidJsonCode(Exception exc) => exc switch
    {
        JsonException => InvalidJsonDecode,
        ContractValidationException => InvalidJsonSchema,
        _ => InvalidJsonOther,
    };
}
