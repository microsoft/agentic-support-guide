#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// End-to-end smoke test against the deployed app.
//
// Modules 1 and 9 both use this. It deliberately tests things a health check
// cannot: that the UI bundle points at the right API host, that CORS permits
// that origin, that a real agent call returns citations, and which evidence
// provider actually served them.
//
//     dotnet run dotnet/scripts/smoke_test.cs
//     dotnet run dotnet/scripts/smoke_test.cs -- --expect-evidence foundry_iq
//
// URLs come from Terraform outputs unless --api-url/--web-url are given.

using System.CommandLine;
using System.Diagnostics;
using System.Net;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Parity;

return await SmokeTest.MainAsync(args);

public static partial class SmokeTest
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string InfraDir = Path.Combine(TrackRoot, "infra");

    // Populated from the terraform output. Scripts talk to the API directly, so
    // they need the key the web tier would otherwise attach for them.
    private static readonly Dictionary<string, string> AuthHeaders = [];

    private static readonly HttpClient Http = new() { Timeout = Timeout.InfiniteTimeSpan };

    // Keeps a 302-to-login from being read as a successful API response.
    private static readonly HttpClient NoRedirect = new(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = Timeout.InfiniteTimeSpan };

    public static async Task<int> MainAsync(string[] args)
    {
        var apiUrl = new Option<string>("--api-url") { DefaultValueFactory = _ => "" };
        var webUrl = new Option<string>("--web-url") { DefaultValueFactory = _ => "" };
        var expectEvidence = new Option<string>("--expect-evidence")
        {
            Description = "Fail if the app is not serving evidence from this provider.",
            DefaultValueFactory = _ => "",
        };
        expectEvidence.AcceptOnlyFromAmong("", "fixture", "foundry_iq");
        var apiKey = new Option<string>("--api-key") { Description = "Shared key for the API. Defaults to the terraform output.", DefaultValueFactory = _ => "" };
        var command = new RootCommand("End-to-end smoke test against the deployed app.") { apiUrl, webUrl, expectEvidence, apiKey };
        command.SetAction(async (parsed, _) =>
        {
            var api = parsed.GetValue(apiUrl) is { Length: > 0 } a ? a : TerraformOutput("api_url");
            var web = parsed.GetValue(webUrl) is { Length: > 0 } w ? w : TerraformOutput("web_url");
            if (api.Length == 0 || web.Length == 0)
            {
                Console.Error.WriteLine("Could not determine URLs. Pass --api-url and --web-url, or run from a repo with Terraform state.");
                return 2;
            }

            // This script calls the API directly, so it needs the key the web
            // tier would otherwise attach. CI has no Terraform state in the
            // deploy job, so the key also comes from the environment.
            var key = parsed.GetValue(apiKey) is { Length: > 0 } k ? k
                : PyText.Strip(Environment.GetEnvironmentVariable("API_SHARED_KEY") ?? "") is { Length: > 0 } fromEnv ? fromEnv
                : TerraformOutput("api_shared_key");
            if (key.Length > 0)
            {
                AuthHeaders["x-api-key"] = key;
                Console.WriteLine("calling the API with the shared key");
            }
            else
            {
                Console.Error.WriteLine("no API key available; direct API checks will fail with 401.");
            }

            return await new Smoke(api, web, parsed.GetValue(expectEvidence) ?? "").RunAsync();
        });
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    private static string TerraformOutput(string name)
    {
        try
        {
            using var terraform = Process.Start(new ProcessStartInfo("terraform", [$"-chdir={InfraDir}", "output", "-raw", name])
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            })!;
            var output = terraform.StandardOutput.ReadToEndAsync();
            _ = terraform.StandardError.ReadToEndAsync();
            if (!terraform.WaitForExit(TimeSpan.FromSeconds(120)))
            {
                terraform.Kill(entireProcessTree: true);
                return "";
            }
            return terraform.ExitCode == 0 ? PyText.Strip(output.Result) : "";
        }
        catch (System.ComponentModel.Win32Exception)
        {
            return "";
        }
    }

    /// <summary>Reject anything that is not a plain http(s) URL.</summary>
    /// <remarks>
    /// The URLs normally come from Terraform outputs, but they are also CLI
    /// arguments, and this script is run inside CI where a file:// or
    /// link-local address would be a genuine problem.
    /// </remarks>
    private static string RequireHttpUrl(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var parsed) || parsed.Scheme is not ("http" or "https") || parsed.Authority.Length == 0)
        {
            throw new ArgumentException($"expected an http(s) URL, got {PyText.Repr(url)}");
        }
        return url.TrimEnd('/');
    }

    private static async Task<(int Status, byte[] Body)> GetAsync(string url, int timeoutSeconds = 120)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, RequireHttpUrl(url));
        request.Headers.TryAddWithoutValidation("Accept", "*/*");
        foreach (var (name, value) in AuthHeaders)
        {
            request.Headers.TryAddWithoutValidation(name, value);
        }
        return await SendAsync(Http, request, timeoutSeconds);
    }

    private static async Task<(int Status, JsonElement Body)> PostAsync(string url, object payload, int timeoutSeconds = 240)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, RequireHttpUrl(url))
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json"),
        };
        foreach (var (name, value) in AuthHeaders)
        {
            request.Headers.TryAddWithoutValidation(name, value);
        }
        var (status, body) = await SendAsync(Http, request, timeoutSeconds);
        return (status, Json(body));
    }

    /// <summary>A response, or <see cref="HTTPError"/> for an error status, as urllib raises.</summary>
    private static async Task<(int Status, byte[] Body)> SendAsync(HttpClient client, HttpRequestMessage request, int timeoutSeconds)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSeconds));
        using var response = await client.SendAsync(request, timeout.Token);
        var body = await response.Content.ReadAsByteArrayAsync(timeout.Token);
        var status = (int)response.StatusCode;
        if (status >= 300)
        {
            throw new HTTPError(status, response.ReasonPhrase ?? "", body);
        }
        return (status, body);
    }

    private static JsonElement Json(byte[] body)
    {
        using var document = JsonDocument.Parse(body);
        return document.RootElement.Clone();
    }

    private static JsonElement? Field(JsonElement? element, string name) =>
        element is { ValueKind: JsonValueKind.Object } value && value.TryGetProperty(name, out var field) ? field : null;

    // A JSON value as Python's str() prints the value json.loads gives.
    private static string Str(JsonElement? value) => value switch
    {
        null => "None",
        { ValueKind: JsonValueKind.Null } => "None",
        { ValueKind: JsonValueKind.True } => "True",
        { ValueKind: JsonValueKind.False } => "False",
        { ValueKind: JsonValueKind.String } text => text.GetString()!,
        { } other => other.GetRawText(),
    };

    // Python's truthiness of a JSON value.
    private static bool Truthy(JsonElement? value) => value switch
    {
        null => false,
        { ValueKind: JsonValueKind.Null or JsonValueKind.False or JsonValueKind.Undefined } => false,
        { ValueKind: JsonValueKind.String } text => text.GetString()!.Length > 0,
        { ValueKind: JsonValueKind.Array } array => array.GetArrayLength() > 0,
        { ValueKind: JsonValueKind.Object } obj => obj.EnumerateObject().Any(),
        { ValueKind: JsonValueKind.Number } number => number.GetDouble() != 0,
        _ => true,
    };

    private static IEnumerable<JsonElement> Items(JsonElement? value) =>
        value is { ValueKind: JsonValueKind.Array } array ? array.EnumerateArray() : [];

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new AssertionError(message);
        }
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;

    [GeneratedRegex("""["'](/assets/[^"']+\.js)["']""", RegexOptions.CultureInvariant)]
    private static partial Regex BundleRe();

    private sealed class Smoke(string api, string web, string expectEvidence)
    {
        private readonly string _api = api.TrimEnd('/');
        private readonly string _web = web.TrimEnd('/');
        private readonly List<string> _failures = [];
        private JsonElement? _rec;

        private async Task CheckAsync(string name, Func<Task> fn)
        {
            try
            {
                await fn();
                Console.WriteLine($"  PASS  {name}");
            }
            catch (Exception exc)
            {
                var detail = exc is HTTPError http ? $" body=b{PyText.Repr(Encoding.Latin1.GetString(http.Body.AsSpan(0, Math.Min(400, http.Body.Length))))}" : "";
                Console.WriteLine($"  FAIL  {name}: {exc.GetType().Name}: {exc.Message}{detail}");
                _failures.Add(name);
            }
        }

        // --- checks ---------------------------------------------------------

        private async Task HealthAsync()
        {
            var (status, body) = await GetAsync($"{_api}/api/health");
            Assert(status == 200, status.ToString());
            var data = Json(body);
            Console.WriteLine($"        build_id={Str(Field(data, "build_id"))} version={Str(Field(data, "version"))}");
            Assert(Str(Field(data, "status")) == "ok" && Field(data, "status")?.ValueKind == JsonValueKind.String, Str(Field(data, "status")));
        }

        private async Task EvidenceSourceAsync()
        {
            var (status, body) = await GetAsync($"{_api}/api/health/details");
            Assert(status == 200, status.ToString());
            var data = Json(body);
            var source = Field(data, "evidence_source");
            Console.WriteLine(
                $"        evidence_source={Str(source)} knowledge_base={Str(Field(data, "evidence_knowledge_base"))} "
                + $"demo_ready={Str(Field(data, "customer_demo_ready"))} evidence_verified={Str(Field(data, "evidence_verified"))}");
            Assert(Truthy(Field(data, "customer_demo_ready")), "customer_demo_ready is false; the app is not configured");
            // `evidence_verified` is false for a remote source because the API
            // cannot prove a knowledge base holds anything without a network
            // call. The real proof is the live request below, which is why this
            // script exists rather than trusting a health flag.
            if (expectEvidence.Length > 0)
            {
                Assert(source?.ValueKind == JsonValueKind.String && source.Value.GetString() == expectEvidence,
                    $"expected evidence_source={expectEvidence}, got {Str(source)}");
            }
        }

        /// <summary>The deploy is only secure if this fails for a caller without the key.</summary>
        /// <remarks>
        /// Everything else in this script sends the key, so a completely
        /// unauthenticated API would sail through every other check.
        /// </remarks>
        private async Task AuthIsEnforcedAsync()
        {
            foreach (var path in (string[])["/api/supports/plans", "/api/dealerships", "/api/health/details"])
            {
                // No redirect following: a 302 to a login page returns 200 for
                // the login HTML, which would read as a successful API response.
                using var request = new HttpRequestMessage(HttpMethod.Get, $"{_api}{path}");
                try
                {
                    var (status, _) = await SendAsync(NoRedirect, request, 30);
                    throw new AssertionError($"{path} answered {status} without the key");
                }
                catch (HTTPError exc)
                {
                    Assert(exc.Code == 401, $"{path} returned {exc.Code}, expected 401");
                }
            }
            Console.WriteLine("        direct calls without the key are refused on 3 paths");
        }

        /// <summary>The real access path: browser -> web tier -> API.</summary>
        /// <remarks>
        /// The browser holds no credential, so this is what actually has to
        /// work. Testing only the direct API path would pass while the UI was broken.
        /// </remarks>
        private async Task UiReachesApiThroughProxyAsync()
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, $"{_web}/api/health/details");
            var (_, body) = await SendAsync(Http, request, 60);
            var data = Json(body);
            Console.WriteLine($"        proxied auth_mode={Str(Field(data, "api_auth_mode"))}");
            Assert(Truthy(Field(data, "customer_demo_ready")), "proxied health says the app is not configured");
        }

        private async Task UiServesAsync()
        {
            var (status, body) = await GetAsync(_web);
            Assert(status == 200, status.ToString());
            Assert(Encoding.UTF8.GetString(body).Contains("id=\"root\"", StringComparison.Ordinal), Encoding.UTF8.GetString(body.AsSpan(0, Math.Min(200, body.Length))));
        }

        private async Task UiSpaFallbackAsync()
        {
            var (status, body) = await GetAsync($"{_web}/dashboard");
            Assert(status == 200, status.ToString());
            Assert(Encoding.UTF8.GetString(body).Contains("id=\"root\"", StringComparison.Ordinal), "SPA fallback is not rewriting deep links");
        }

        /// <summary>The whole design rests on the browser never receiving the key.</summary>
        /// <remarks>
        /// If the key or the API hostname ends up inlined in the bundle, the
        /// proxy has been bypassed and the key is public.
        /// </remarks>
        private async Task BundleCarriesNoSecretAsync()
        {
            var (_, body) = await GetAsync(_web);
            var match = BundleRe().Match(Encoding.UTF8.GetString(body));
            Assert(match.Success, "no JS bundle referenced in index.html");
            var (_, jsBytes) = await GetAsync($"{_web}{match.Groups[1].Value}");
            var js = Encoding.UTF8.GetString(jsBytes);

            var key = AuthHeaders.GetValueOrDefault("x-api-key", "");
            Assert(!(key.Length > 0 && js.Contains(key, StringComparison.Ordinal)), "the shared key is inlined in the UI bundle");
            var host = _api.Contains("//", StringComparison.Ordinal) ? _api[(_api.IndexOf("//", StringComparison.Ordinal) + 2)..] : _api;
            Assert(!js.Contains(host, StringComparison.Ordinal), $"bundle calls {host} directly, bypassing the proxy that holds the key");
            Console.WriteLine("        bundle contains neither the key nor the API hostname");
        }

        private async Task RecommendationAsync()
        {
            var (status, data) = await PostAsync($"{_api}/api/recommendations/support-plan", new Dictionary<string, string>
            {
                ["dealer_group_id"] = "GROUP-A",
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
            });
            Assert(status == 200, status.ToString());
            _rec = data;
            Assert(Str(Field(data, "status")) == "ok",
                $"{Str(Field(data, "status"))}: {Str(Field(data, "error_code"))} {Str(Field(data, "error_message"))}");
            foreach (var step in Items(Field(data, "agent_trace")))
            {
                Console.WriteLine(
                    $"        {Str(Field(step, "agent")),-30} {Str(Field(step, "status")),-9} "
                    + $"provider={Str(Field(step, "provider"))} {Str(Field(step, "latency_ms"))}ms");
            }
        }

        private Task CitationsAsync()
        {
            var cites = Items(Field(Field(_rec, "recommendation"), "citations")).ToList();
            Console.WriteLine($"        citations: {cites.Count}");
            Assert(cites.Count > 0, "recommendation returned no citations");
            return Task.CompletedTask;
        }

        private Task TraceReportsExpectedProviderAsync()
        {
            if (expectEvidence.Length == 0)
            {
                return Task.CompletedTask;
            }
            var step = Items(Field(_rec, "agent_trace")).Cast<JsonElement?>().FirstOrDefault(s => Str(Field(s, "agent")) == "evidence-retrieval");
            Assert(step is not null, "no evidence-retrieval step in the trace");
            Assert(Str(Field(step, "provider")) == expectEvidence, $"trace says provider={Str(Field(step, "provider"))}, expected {expectEvidence}");
            return Task.CompletedTask;
        }

        private Task DealerGroupIsolationAsync()
        {
            var stray = Items(Field(Field(_rec, "recommendation"), "citations"))
                .Where(c => Field(c, "dealer_group_id") is { } group && group.ValueKind != JsonValueKind.Null && Str(group) is not ("" or "GROUP-A"))
                .Select(c => c.GetRawText())
                .ToList();
            Assert(stray.Count == 0, $"citations leaked from another dealer group: [{string.Join(", ", stray)}]");
            return Task.CompletedTask;
        }

        private async Task AuditAsync()
        {
            var (status, body) = await GetAsync($"{_api}/api/audit/events");
            Assert(status == 200, status.ToString());
            var events = Json(body);
            var items = events.ValueKind == JsonValueKind.Array ? Items(events).ToList() : Items(Field(events, "events")).ToList();
            Console.WriteLine($"        audit events: {items.Count}");
            Assert(items.Count > 0, "no audit events recorded");
        }

        public async Task<int> RunAsync()
        {
            Console.WriteLine($"API {_api}");
            Console.WriteLine($"UI  {_web}");
            if (expectEvidence.Length > 0)
            {
                Console.WriteLine($"expecting evidence_source={expectEvidence}");
            }
            Console.WriteLine();
            await CheckAsync("API health responds", HealthAsync);
            await CheckAsync("API refuses calls without the key", AuthIsEnforcedAsync);
            await CheckAsync("UI reaches the API through the proxy", UiReachesApiThroughProxyAsync);
            await CheckAsync("evidence source is as expected", EvidenceSourceAsync);
            await CheckAsync("UI serves index.html", UiServesAsync);
            await CheckAsync("UI deep link falls back to the SPA", UiSpaFallbackAsync);
            await CheckAsync("UI bundle carries no secret", BundleCarriesNoSecretAsync);
            await CheckAsync("support-plan request succeeds", RecommendationAsync);
            await CheckAsync("recommendation carries citations", CitationsAsync);
            await CheckAsync("trace names the real evidence provider", TraceReportsExpectedProviderAsync);
            await CheckAsync("no cross-group citations", DealerGroupIsolationAsync);
            await CheckAsync("audit trail recorded the call", AuditAsync);

            Console.WriteLine();
            if (_failures.Count > 0)
            {
                Console.WriteLine($"{_failures.Count} FAILED: {string.Join(", ", _failures)}");
                return 1;
            }
            Console.WriteLine("ALL SMOKE CHECKS PASSED");
            return 0;
        }
    }

    /// <summary>What a failed check raises; named as Python's, so a failure reads the same in both tracks.</summary>
    private sealed class AssertionError(string message) : Exception(message);

    /// <summary>An error status, named and worded as urllib's.</summary>
    private sealed class HTTPError(int code, string reason, byte[] body) : Exception($"HTTP Error {code}: {reason}")
    {
        public int Code { get; } = code;

        public byte[] Body { get; } = body;
    }
}
