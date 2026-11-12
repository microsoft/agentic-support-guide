using System.ClientModel;
using System.Net;

namespace AgenticSupportGuide.Api.FoundryAgents;

/// <summary>
/// Map Microsoft Agent Framework / OpenAI failures onto the app error taxonomy.
/// </summary>
/// <remarks>
/// The OpenAI client surfaces an HTTP failure as a <see cref="ClientResultException"/>
/// carrying the status, and the Agent Framework and Microsoft.Extensions.AI
/// layers may wrap it. The inner-exception chain is walked so a wrapped
/// failure still classifies. A content-filter refusal is a 400 whose error
/// code names the filter.
/// </remarks>
public static class ErrorMapping
{
    // Walk a bounded number of inner exceptions so a nested wrap still classifies.
    private const int MaxCauseDepth = 5;

    /// <summary>Classify an exception without leaking provider text.</summary>
    public static FoundryProviderException MapProviderError(Exception exc)
    {
        if (exc is FoundryProviderException known)
        {
            return known;
        }

        var chain = Causes(exc);
        var names = ClassNames(chain);
        var text = string.Join(" ", chain.Select(e => e.Message)).ToLowerInvariant();
        var status = StatusCode(chain);

        if (names.Any(name => name.Contains("ContentFilterException", StringComparison.Ordinal))
            || text.Contains("content_filter", StringComparison.Ordinal))
        {
            return new ContentFilterException("CONTENT_FILTER", "Remote agent request was blocked by content safety.");
        }

        if (chain.Any(e => e is TimeoutException) || exc is TaskCanceledException)
        {
            return new FoundryTimeoutException("RUN_TIMEOUT", "Remote agent run timed out.");
        }

        if (status == 429)
        {
            return new ThrottledException("THROTTLED", "Remote agent request was throttled. Retry shortly.");
        }

        if (status is 401 or 403
            // RBAC assignments take minutes to propagate; learners hit this first.
            || text.Contains("does not have authorization", StringComparison.Ordinal))
        {
            return new AuthException(
                "AUTH_DENIED",
                "Azure rejected the credential. Run 'az login', confirm the subscription, and allow a few minutes for RBAC propagation.");
        }

        return new FoundryRunException("PROVIDER_ERROR", "Remote agent call failed.");
    }

    private static List<Exception> Causes(Exception exc)
    {
        var chain = new List<Exception> { exc };
        var current = exc;
        for (var i = 0; i < MaxCauseDepth && current.InnerException is not null; i++)
        {
            current = current.InnerException;
            chain.Add(current);
        }
        return chain;
    }

    private static HashSet<string> ClassNames(List<Exception> chain)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in chain)
        {
            for (var type = item.GetType(); type is not null; type = type.BaseType)
            {
                names.Add(type.Name);
            }
        }
        return names;
    }

    private static int? StatusCode(List<Exception> chain)
    {
        foreach (var item in chain)
        {
            switch (item)
            {
                case ClientResultException { Status: > 0 } result:
                    return result.Status;
                case HttpRequestException { StatusCode: HttpStatusCode code }:
                    return (int)code;
            }
        }
        return null;
    }
}
