using System.Net.Http.Json;
using System.Reflection;
using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Parity;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.Routing;
using Microsoft.Extensions.DependencyInjection;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Caller authentication.
/// </summary>
/// <remarks>
/// The API is reachable on a public hostname, so the shared key is what stops
/// it being called directly. These tests send real headers rather than
/// disabling the check, so the comparison path actually runs.
///
/// There is deliberately no per-user authorization to test: the web tier
/// attaches the key for whoever asks, so anyone who can reach the UI can reach
/// the API through it. That is a property of the design, recorded here so it
/// stays a decision rather than an assumption.
/// </remarks>
public sealed class AuthTests
{
    private static readonly Dictionary<string, string> RecommendationBody = new()
    {
        ["dealer_group_id"] = "GROUP-A",
        ["dealership_id"] = "DLR-0001",
        ["category"] = "lead-response",
        ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
    };

    // Reachable without a key by design: deploy-app.ps1 and CI poll this to find
    // out which build is serving, before the web tier is up. Adding a route here
    // is a deliberate act.
    private static readonly HashSet<string> AnonymousPaths = ["/api/health"];

    private static bool RequiresKey(RouteEndpoint route) => route.Metadata.GetMetadata<ApiKeyRequired>() is not null;

    // TestApp keeps the app's service provider to itself, so a second host over
    // the same environment is asked for its endpoints.
    private static List<RouteEndpoint> RouteTable()
    {
        using var app = TestApp.Start();
        using var host = new WebApplicationFactory<Program>().WithWebHostBuilder(builder => builder.UseEnvironment("Production"));
        return [.. host.Services.GetRequiredService<EndpointDataSource>().Endpoints.OfType<RouteEndpoint>()];
    }

    // Sends exactly this key, in place of the one the client attaches by default.
    private static async Task<HttpResponseMessage> SendAsync(TestApp client, HttpMethod method, string path, string apiKey, object? json = null)
    {
        using var request = new HttpRequestMessage(method, path);
        request.Headers.Add(Auth.ApiKeyHeader, apiKey);
        if (json is not null)
        {
            request.Content = JsonContent.Create(json);
        }
        return await client.Client.SendAsync(request, TestContext.Current.CancellationToken);
    }

    private static async Task<int> StatusAsync(TestApp client, string path)
    {
        using var response = await client.Client.GetAsync(path, TestContext.Current.CancellationToken);
        return (int)response.StatusCode;
    }

    /// <summary>Catches a new route added without the key check.</summary>
    /// <remarks>
    /// Asserted against the route table rather than by calling each endpoint:
    /// a request can be rejected for its body before the key is looked at,
    /// which would make an unprotected route look protected.
    /// </remarks>
    [Fact]
    public void Every_route_requires_the_key_or_is_explicitly_anonymous()
    {
        // The OpenAPI document is an endpoint too, but Microsoft.AspNetCore.OpenApi
        // maps it rather than the app, so only routes whose handler the app
        // declares are checked here. The next test pins the docs routes shut.
        var apiRoutes = RouteTable()
            .Where(route => (route.RoutePattern.RawText ?? "").StartsWith("/api/", StringComparison.Ordinal)
                && route.Metadata.GetMetadata<MethodInfo>()?.DeclaringType?.Assembly == typeof(Endpoints).Assembly)
            .ToList();

        // Without this the test passes silently if route introspection ever breaks.
        Assert.True(apiRoutes.Count >= 12, $"only found {apiRoutes.Count} routes to check");

        var unprotected = apiRoutes
            .Where(route => !AnonymousPaths.Contains(route.RoutePattern.RawText!) && !RequiresKey(route))
            .Select(route =>
                $"{PyText.ReprList((route.Metadata.GetMetadata<IHttpMethodMetadata>()?.HttpMethods ?? []).Order(StringComparer.Ordinal))} {route.RoutePattern.RawText}")
            .Order(StringComparer.Ordinal)
            .ToList();
        Assert.True(unprotected.Count == 0, $"routes missing the API key check: {PyText.ReprList(unprotected)}");
    }

    /// <summary>The docs routes are not the app's own routes, so the check above cannot see them.</summary>
    /// <remarks>
    /// Microsoft.AspNetCore.OpenApi maps /api/openapi.json and the Swagger UI
    /// middleware serves /api/docs, both outside the filter that carries the
    /// key check. On App Service they would hand the entire schema to anyone;
    /// this pins them shut.
    /// </remarks>
    [Fact]
    public async Task No_unguarded_non_api_routes_are_served_on_app_service()
    {
        using (var app = TestApp.Start(new Dictionary<string, string> { [Auth.AppServiceMarker] = "app-asg-api-example" }))
        {
            Assert.True(await StatusAsync(app, "/api/openapi.json") == 404, "OpenAPI schema is exposed on App Service");
            Assert.True(await StatusAsync(app, "/api/docs") == 404, "Swagger UI is exposed on App Service");
        }

        // Still available on a laptop, which is where learners read them.
        using var local = TestApp.Start();
        Assert.NotEqual(404, await StatusAsync(local, "/api/docs"));
    }

    [Fact]
    public async Task Request_without_a_key_is_rejected()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await SendAsync(client, HttpMethod.Post, "/api/recommendations/support-plan", "", RecommendationBody);
        Assert.Equal(401, (int)response.StatusCode);
    }

    [Fact]
    public async Task Wrong_key_is_rejected()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await SendAsync(client, HttpMethod.Get, "/api/supports/plans", "not-the-key");
        Assert.Equal(401, (int)response.StatusCode);
    }

    [Fact]
    public async Task Correct_key_is_accepted()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await SendAsync(client, HttpMethod.Get, "/api/supports/plans", TestApp.TestApiKey);
        Assert.Equal(200, (int)response.StatusCode);
    }

    /// <summary>deploy-app.ps1 polls health to detect stale builds before the UI is up.</summary>
    [Fact]
    public async Task Health_stays_anonymous()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await SendAsync(client, HttpMethod.Get, "/api/health", "");
        Assert.Equal(200, (int)response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<JsonNode>(TestContext.Current.CancellationToken);
        Assert.Equal("ok", body!["status"]!.GetValue<string>());
    }

    /// <summary>It reports evidence source, knowledge base and readiness flags.</summary>
    /// <remarks>
    /// That is reconnaissance for anyone choosing what to attack, and unlike
    /// <c>/api/health</c> nothing in the deploy path needs it anonymously.
    /// </remarks>
    [Fact]
    public async Task Health_details_needs_the_key()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await SendAsync(client, HttpMethod.Get, "/api/health/details", "");
        Assert.Equal(401, (int)response.StatusCode);
    }

    /// <summary>Forgetting the setting must not be the same as turning auth off.</summary>
    /// <remarks>
    /// Locally a missing key means "the API behind the Vite dev proxy". On App
    /// Service it means the API is open on a public hostname, so it fails closed.
    /// </remarks>
    [Fact]
    public async Task Api_refuses_to_serve_unauthenticated_on_app_service()
    {
        using var c = Conftest.MakeDefaultClient();
        Environment.SetEnvironmentVariable("API_SHARED_KEY", null);
        Environment.SetEnvironmentVariable(Auth.AppServiceMarker, null);
        try
        {
            Assert.Equal("unprotected", Auth.ApiAuthMode());
            Assert.Equal(200, await StatusAsync(c, "/api/supports/plans"));

            Environment.SetEnvironmentVariable(Auth.AppServiceMarker, "app-asg-api-example");
            Assert.Equal("misconfigured", Auth.ApiAuthMode());
            Assert.Equal(503, await StatusAsync(c, "/api/supports/plans"));
        }
        finally
        {
            Environment.SetEnvironmentVariable(Auth.AppServiceMarker, null);
            Environment.SetEnvironmentVariable("API_SHARED_KEY", TestApp.TestApiKey);
        }
    }

    /// <summary>The UI has no identity, so the roster has to be served to it.</summary>
    [Fact]
    public async Task Dealer_groups_come_from_the_api_not_the_bundle()
    {
        using var client = Conftest.MakeDefaultClient();
        using var response = await SendAsync(client, HttpMethod.Get, "/api/supports/options", TestApp.TestApiKey);
        var body = await response.Content.ReadFromJsonAsync<JsonNode>(TestContext.Current.CancellationToken);
        string[] expected = ["GROUP-A", "GROUP-B", "GROUP-DEMO"];
        Assert.Equal(expected, body!["dealer_groups"]!.AsArray().Select(group => group!.GetValue<string>()));
    }
}
