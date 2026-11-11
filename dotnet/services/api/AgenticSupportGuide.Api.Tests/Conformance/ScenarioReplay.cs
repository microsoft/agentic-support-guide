using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.FoundryAgents;

namespace AgenticSupportGuide.Api.Tests.Conformance;

/// <summary>
/// Replays one recorded scenario against this track's app and records what
/// happened in the same shape the Python generator used.
/// </summary>
public static partial class ScenarioReplay
{
    private const string WrongKey = "not-the-key";

    private static readonly string[] RecordedHeaders =
    [
        "content-type",
        "www-authenticate",
        "allow",
        "location",
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-allow-credentials",
    ];

    // Typed provider failures a canned reply can raise, by the Python class name.
    private static readonly Dictionary<string, Func<Exception>> ProviderErrors = new()
    {
        ["ContentFilterError"] = () => new ContentFilterException("CONTENT_FILTER", "blocked"),
        ["ThrottledError"] = () => new ThrottledException("THROTTLED", "429"),
        ["FoundryTimeoutError"] = () => new FoundryTimeoutException("RUN_TIMEOUT", "timed out"),
        ["FoundryRunError"] = () => new FoundryRunException("RUN_FAILED", "run failed"),
        ["AuthError"] = () => new AuthException("AUTH_DENIED", "denied"),
    };

    public sealed record StepResult(JsonObject Request, JsonObject Response, JsonArray ModelCalls);

    public static async Task<List<StepResult>> RunAsync(JsonObject scenario)
    {
        var config = scenario["config"]!.AsObject();
        var environment = new Dictionary<string, string> { ["BUILD_ID"] = "conformance" };
        var fake = config["provider"]?.GetValue<string>() == "fake";
        if (fake)
        {
            environment["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"] = FakeChatClientFactory.DefaultEndpoint;
        }
        var apiKey = config["api_key"]?.GetValue<string>();
        if (!string.IsNullOrEmpty(apiKey))
        {
            environment["API_SHARED_KEY"] = apiKey;
        }
        if (config["app_service"]?.GetValue<bool>() == true)
        {
            environment["WEBSITE_SITE_NAME"] = "app-asg-api-conformance";
        }
        if (config["demo_reset_enabled"]?.GetValue<bool>() == true)
        {
            environment["DEMO_RESET_ENABLED"] = "true";
        }

        var factory = BuildFactory(scenario["replies"]?.AsObject());
        using var app = TestApp.Start(
            environment,
            runtime: fake ? () => new MafAgentRuntime(RoleDefinitions.LoadRoleDefinitions(), factory.InvokeAsync) : null);

        var steps = new List<StepResult>();
        foreach (var stepNode in scenario["steps"]!.AsArray())
        {
            var step = stepNode!["request"]!.AsObject();
            var start = factory.Calls().Count;
            var (response, tail) = await SendAsync(app.Client, step, apiKey);
            var recorded = await RecordResponseAsync(response, tail);
            steps.Add(new StepResult(step, Normalize(recorded)!.AsObject(), Normalize(ModelCalls(factory, start))!.AsArray()));
        }
        return steps;
    }

    /// <summary>
    /// Whether a browser would let the request through after this preflight.
    /// </summary>
    /// <remarks>
    /// The two frameworks answer a preflight differently (status codes and
    /// header lists), so preflights are compared by this verdict alone. See
    /// <c>cors-preflight</c> in conformance/allowed_differences.yaml.
    /// </remarks>
    public static bool PreflightAllowed(JsonObject request, JsonObject response)
    {
        var headers = request["headers"]?.AsObject();
        var origin = headers?["Origin"]?.GetValue<string>() ?? "";
        var method = headers?["Access-Control-Request-Method"]?.GetValue<string>() ?? "";
        var requestedHeaders = (headers?["Access-Control-Request-Headers"]?.GetValue<string>() ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var status = response["status"]!.GetValue<int>();
        var responseHeaders = response["headers"]!.AsObject();
        string Header(string name) => responseHeaders[name]?.GetValue<string>() ?? "";
        static HashSet<string> List(string value) =>
            value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToHashSet(StringComparer.OrdinalIgnoreCase);

        return status is >= 200 and < 300
            && (Header("access-control-allow-origin") == origin || Header("access-control-allow-origin") == "*")
            && List(Header("access-control-allow-methods")).Contains(method)
            && requestedHeaders.All(List(Header("access-control-allow-headers")).Contains);
    }

    public static bool IsPreflight(JsonObject request) =>
        request["method"]?.GetValue<string>() == "OPTIONS"
        && request["headers"]?.AsObject().ContainsKey("Access-Control-Request-Method") == true;

    private static FakeChatClientFactory BuildFactory(JsonObject? replies)
    {
        var factory = new FakeChatClientFactory();
        foreach (var (role, queue) in replies ?? [])
        {
            foreach (var item in queue!.AsArray())
            {
                var reply = item!.AsObject();
                if (reply["error"] is { } error)
                {
                    factory.RegisterError(role, ProviderErrors[error.GetValue<string>()]());
                }
                else if (reply["text"] is { } text)
                {
                    factory.RegisterResponse(role, text.GetValue<string>());
                }
                else
                {
                    factory.RegisterResponse(role, JsonSerializer.Deserialize<JsonElement>(reply["json"]!.ToJsonString()));
                }
            }
        }
        return factory;
    }

    private static async Task<(HttpResponseMessage Response, int? Tail)> SendAsync(HttpClient client, JsonObject step, string? apiKey)
    {
        var path = step["path"]!.GetValue<string>();
        int? tail = null;
        var query = "";
        var q = path.IndexOf('?');
        if (q >= 0)
        {
            query = path[(q + 1)..];
            path = path[..q];
            var parts = query.Split('&', StringSplitOptions.RemoveEmptyEntries);
            var tailPart = parts.FirstOrDefault(p => p.StartsWith("tail=", StringComparison.Ordinal));
            tail = tailPart is null ? null : int.Parse(tailPart[5..], CultureInfo.InvariantCulture);
            query = string.Join("&", parts.Where(p => !p.StartsWith("tail=", StringComparison.Ordinal)));
        }
        var url = query.Length > 0 ? $"{path}?{query}" : path;
        var request = new HttpRequestMessage(new HttpMethod(step["method"]!.GetValue<string>()), url);

        foreach (var (name, value) in step["headers"]?.AsObject() ?? [])
        {
            request.Headers.TryAddWithoutValidation(name, value!.GetValue<string>());
        }
        var auth = step["auth"]?.GetValue<string>() ?? "key";
        if (auth == "key" && !string.IsNullOrEmpty(apiKey))
        {
            request.Headers.TryAddWithoutValidation("x-api-key", apiKey);
        }
        else if (auth == "wrong")
        {
            request.Headers.TryAddWithoutValidation("x-api-key", WrongKey);
        }

        if (step["body"] is { } body)
        {
            request.Content = new StringContent(body.GetValue<string>(), Encoding.UTF8);
            request.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(step["content_type"]?.GetValue<string>() ?? "application/json");
        }
        else if (step["json"] is { } json)
        {
            request.Content = new StringContent(json.ToJsonString(), Encoding.UTF8, "application/json");
        }
        return (await client.SendAsync(request), tail);
    }

    private static async Task<JsonObject> RecordResponseAsync(HttpResponseMessage response, int? tail)
    {
        var headers = new JsonObject();
        foreach (var name in RecordedHeaders)
        {
            if (response.Headers.TryGetValues(name, out var values) || response.Content.Headers.TryGetValues(name, out values))
            {
                var value = string.Join(", ", values);
                if (name == "location")
                {
                    // The test client's host is not the app's; keep where it points.
                    var target = new Uri(value, UriKind.RelativeOrAbsolute);
                    value = target.IsAbsoluteUri ? target.PathAndQuery : value;
                }
                headers[name] = value;
            }
        }
        var record = new JsonObject { ["status"] = (int)response.StatusCode, ["headers"] = headers };
        var text = await response.Content.ReadAsStringAsync();
        if (text.Length == 0)
        {
            record["body"] = "";
            return record;
        }
        var contentType = headers["content-type"]?.GetValue<string>() ?? "";
        if (contentType.StartsWith("application/json", StringComparison.Ordinal))
        {
            var body = JsonNode.Parse(text)!;
            record["json"] = tail is { } count ? Tail(body.AsObject(), count) : body;
        }
        else
        {
            record["body_kind"] = contentType.Split(';')[0];
        }
        return record;
    }

    // Keep the last `count` rows of a list response; the head is in another golden.
    private static JsonNode Tail(JsonObject body, int count)
    {
        foreach (var key in new[] { "events", "plans" })
        {
            if (body[key] is JsonArray rows)
            {
                var kept = rows.Skip(Math.Max(0, rows.Count - count)).Select(r => r?.DeepClone()).ToArray();
                body[key] = new JsonArray(kept);
                return body;
            }
        }
        return body;
    }

    private static JsonArray ModelCalls(FakeChatClientFactory factory, int start)
    {
        var calls = new JsonArray();
        foreach (var call in factory.Calls().Skip(start))
        {
            calls.Add(new JsonObject
            {
                ["role"] = call.Role,
                ["model"] = call.Model,
                ["instructions_sha256"] = Sha256(call.Instructions),
                ["temperature"] = call.Temperature,
                ["max_output_tokens"] = call.MaxOutputTokens,
                ["store"] = call.Store,
                ["response_model"] = call.ResponseModel?.Name,
                ["user_message"] = call.UserMessage,
            });
        }
        return calls;
    }

    public static string Sha256(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));

    // --- Normalisation: the same placeholders the Python generator writes ---

    [GeneratedRegex(@"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
    private static partial Regex Uuid();

    [GeneratedRegex(@"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")]
    private static partial Regex Iso();

    private static JsonNode? Normalize(JsonNode? value, string? key = null, JsonObject? parent = null)
    {
        switch (value)
        {
            case JsonObject obj:
                var result = new JsonObject();
                foreach (var (k, v) in obj)
                {
                    result[k] = Normalize(v, k, obj);
                }
                return result;
            case JsonArray array:
                return new JsonArray(array.Select(item => Normalize(item, key, parent)).ToArray());
            case JsonValue v when v.GetValueKind() == JsonValueKind.String:
                var text = v.GetValue<string>();
                if (Uuid().IsMatch(text))
                {
                    return "<uuid>";
                }
                return Iso().Replace(text, m => IsRecent(m.Value) ? "<now>" : m.Value);
            case JsonValue v when v.GetValueKind() == JsonValueKind.Number && key == "latency_ms":
                return "<ms>";
            case JsonValue v when v.GetValueKind() == JsonValueKind.Number
                && key == "duration_ms"
                && parent is not null
                && (parent["event_id"]?.GetValue<string>() ?? "").StartsWith("AUD-R", StringComparison.Ordinal)
                && parent["context"]?.GetValue<string>() == "plan-generation":
                return "<ms>";
            default:
                return value?.DeepClone();
        }
    }

    private static bool IsRecent(string stamp)
    {
        var moment = DateTime.ParseExact(stamp, "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
        return (DateTime.UtcNow - moment).Duration() < TimeSpan.FromDays(2);
    }
}
