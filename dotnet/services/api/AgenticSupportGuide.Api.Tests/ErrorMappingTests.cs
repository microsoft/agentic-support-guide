using System.ClientModel;
using AgenticSupportGuide.Api.FoundryAgents;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Error-mapping tests.
/// </summary>
/// <remarks>
/// Agent Framework wraps provider failures in other exceptions, so these tests
/// build the real inner-exception chain. A test that classified a bare
/// <c>RateLimitError</c> would pass while production silently bucketed every
/// throttle as a generic provider error.
/// </remarks>
public sealed class ErrorMappingTests
{
    /// <summary>Stand-in with the same wrapping shape Agent Framework uses.</summary>
    private sealed class ChatClientException(string message, Exception innerException) : Exception(message, innerException);

    // The OpenAI client reports an HTTP failure as a ClientResultException
    // carrying the status, so each status stand-in is one.
    private sealed class RateLimitError : ClientResultException
    {
        public RateLimitError(string message) : base(message) => Status = 429;
    }

    private sealed class AuthenticationError : ClientResultException
    {
        public AuthenticationError(string message) : base(message) => Status = 401;
    }

    private sealed class PermissionDeniedError : ClientResultException
    {
        public PermissionDeniedError(string message) : base(message) => Status = 403;
    }

    // The client's own timeout surfaces as a TimeoutException.
    private sealed class APITimeoutError(string message) : TimeoutException(message);

    private sealed class OpenAIContentFilterException(string message) : Exception(message);

    /// <summary>Reproduce <c>throw new ChatClientException(..., inner)</c>.</summary>
    private static Exception Wrapped(Exception inner)
    {
        try
        {
            try
            {
                throw inner;
            }
            catch (Exception exc)
            {
                throw new ChatClientException($"service failed: {exc.Message}", exc);
            }
        }
        catch (ChatClientException outer)
        {
            return outer;
        }
    }

    public static TheoryData<Exception, Type> WrappedExceptions() => new()
    {
        { new RateLimitError("429 too many requests"), typeof(ThrottledException) },
        { new AuthenticationError("401 unauthorized"), typeof(AuthException) },
        { new PermissionDeniedError("403 forbidden"), typeof(AuthException) },
        { new APITimeoutError("timed out"), typeof(FoundryTimeoutException) },
        { new OpenAIContentFilterException("blocked"), typeof(ContentFilterException) },
        { new ArgumentException("something else"), typeof(FoundryRunException) },
    };

    [Theory]
    [MemberData(nameof(WrappedExceptions))]
    public void Wrapped_exceptions_classify_through_cause(Exception inner, Type expected)
    {
        var mapped = ErrorMapping.MapProviderError(Wrapped(inner));
        Assert.IsType(expected, mapped, exactMatch: false);
    }

    [Fact]
    public void Asyncio_timeout_maps_to_timeout()
    {
        Assert.IsType<FoundryTimeoutException>(ErrorMapping.MapProviderError(new TimeoutException()), exactMatch: false);
    }

    [Fact]
    public void Already_mapped_error_passes_through()
    {
        var original = new ThrottledException("THROTTLED", "slow down");
        Assert.Same(original, ErrorMapping.MapProviderError(original));
    }

    [Fact]
    public void Mapped_errors_never_leak_provider_text()
    {
        var secret = "prompt text and endpoint https://secret.example.invalid";
        var mapped = ErrorMapping.MapProviderError(Wrapped(new ArgumentException(secret)));
        Assert.DoesNotContain(secret, mapped.SafeMessage, StringComparison.Ordinal);
        Assert.DoesNotContain("secret.example.invalid", mapped.ToString(), StringComparison.Ordinal);
    }

    /// <summary>Learners hit this on first run; the message must tell them what to do.</summary>
    [Fact]
    public void Auth_message_mentions_rbac_propagation()
    {
        var mapped = ErrorMapping.MapProviderError(Wrapped(new AuthenticationError("401")));
        Assert.Contains("az login", mapped.SafeMessage, StringComparison.Ordinal);
        Assert.Contains("RBAC", mapped.SafeMessage, StringComparison.Ordinal);
    }
}
