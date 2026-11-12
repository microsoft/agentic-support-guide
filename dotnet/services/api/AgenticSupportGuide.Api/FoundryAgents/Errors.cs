namespace AgenticSupportGuide.Api.FoundryAgents;

/// <summary>
/// Generic Foundry provider failure.
/// </summary>
/// <remarks>
/// None of these errors carry raw model text. They map SDK failures into safe,
/// coded application errors the workflow can surface without leaking prompts,
/// completions or endpoint details.
/// </remarks>
public class FoundryProviderException(string code, string message) : Exception($"{code}: {message}")
{
    public string Code { get; } = code;

    public string SafeMessage { get; } = message;
}

/// <summary>Foundry project/agents are not configured.</summary>
public sealed class ConfigurationException(string code, string message) : FoundryProviderException(code, message);

/// <summary>The model call timed out in the client SDK.</summary>
public sealed class FoundryTimeoutException(string code, string message) : FoundryProviderException(code, message);

/// <summary>The remote run finished in a non-completed state (failed/cancelled/expired).</summary>
public sealed class FoundryRunException(string code, string message) : FoundryProviderException(code, message);

/// <summary>The remote run entered requires_action. Not supported in this build.</summary>
public sealed class RequiresActionException(string code, string message) : FoundryProviderException(code, message);

/// <summary>The provider blocked the request via content safety.</summary>
public sealed class ContentFilterException(string code, string message) : FoundryProviderException(code, message);

/// <summary>The provider throttled the request (429/quota).</summary>
public sealed class ThrottledException(string code, string message) : FoundryProviderException(code, message);

/// <summary>The provider rejected the credential (401/403).</summary>
public sealed class AuthException(string code, string message) : FoundryProviderException(code, message);
