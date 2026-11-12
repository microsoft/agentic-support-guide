using System.Security.Cryptography;
using System.Text;

namespace AgenticSupportGuide.Api;

/// <summary>
/// Caller authentication for the API.
/// </summary>
/// <remarks>
/// The API sits behind the web tier, which holds a shared key and attaches it
/// server-side. The browser never sees the key: a React bundle cannot keep a
/// secret, so anything the SPA carried would be readable in DevTools.
///
/// This authenticates the *web tier*, not a person. There is no user identity
/// here and therefore no per-caller dealer group authorization - the UI chooses
/// a dealer group and the API validates that it exists. In this workshop each
/// user deploys their own stack, so there is no second user to isolate from.
/// Anyone who can reach the web tier can drive the API through it; the key only
/// stops the API's own hostname being called directly.
/// </remarks>
public static class Auth
{
    public const string ApiKeyHeader = "x-api-key";
    public const string ApiKeyEnv = "API_SHARED_KEY";

    // Set by App Service on every worker. Its presence is the difference between
    // "a laptop" and "reachable from the internet".
    public const string AppServiceMarker = "WEBSITE_SITE_NAME";

    public static string ConfiguredKey() => (Environment.GetEnvironmentVariable(ApiKeyEnv) ?? "").Trim();

    public static bool RunningOnAppService() => !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(AppServiceMarker));

    /// <summary>What <c>/api/health/details</c> reports about inbound protection.</summary>
    public static string ApiAuthMode()
    {
        if (ConfiguredKey().Length > 0)
        {
            return "shared_key";
        }
        return RunningOnAppService() ? "misconfigured" : "unprotected";
    }

    /// <summary>
    /// Reject anything that did not come through the web tier. Null means allowed.
    /// </summary>
    /// <remarks>
    /// Fails closed: a deployed app with no key configured refuses every request
    /// rather than serving them all. An unauthenticated API on a public hostname
    /// is the failure this exists to prevent, so it must not be what happens when
    /// someone forgets a setting.
    /// </remarks>
    public static IResult? RequireApiKey(HttpRequest request)
    {
        var expected = ConfiguredKey();
        if (expected.Length == 0)
        {
            if (RunningOnAppService())
            {
                return Http.Detail(503, "API_SHARED_KEY is not configured; refusing to serve unauthenticated.");
            }
            // Local development: the API behind the Vite dev proxy, no key needed.
            return null;
        }

        // The first value, as Starlette reads a repeated header.
        var presented = request.Headers.TryGetValue(ApiKeyHeader, out var values) && values.Count > 0 ? values[0] ?? "" : "";
        // A fixed-time comparison, so a wrong key cannot be narrowed down by response timing.
        if (!CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(presented), Encoding.UTF8.GetBytes(expected)))
        {
            return Http.Detail(401, "Missing or invalid API key.", ("WWW-Authenticate", ApiKeyHeader));
        }
        return null;
    }
}
