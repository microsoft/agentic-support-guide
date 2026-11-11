#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Deploy the Support Explainer to Foundry as a hosted agent.
//
// The whole point of this script is that nothing is hidden. It prints the
// zip contents, the definition it is sending, and then polls the build and
// prints the real status and error, so a failed deploy is diagnosable rather
// than mysterious.
//
// Flow:
//   1. Compose instructions from agents/support-explainer/agent.md
//   2. Stage the project, instructions.md and the shared code in one flat folder
//   3. The SDK zips that folder and sends its SHA-256 (Foundry uses it for
//      integrity and dedup)
//   4. CreateAgentVersionFromCode -> Foundry restores and publishes remotely
//   5. Poll until the version is running or failed
//
// Usage:
//     dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias>            # dry run
//     dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --apply
//     dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --status
//     dotnet run dotnet/scripts/publish_hosted_agent.cs -- --suffix <your-alias> --delete

using System.ClientModel;
using System.ClientModel.Primitives;
using System.CommandLine;
using System.Diagnostics;
using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;
using Azure.AI.Projects.Agents;

// The tests compile this file too, and call its methods directly.
#if !UNDER_TEST
return await PublishHostedAgent.MainAsync(args);
#endif

public static partial class PublishHostedAgent
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string EnvFile = Path.Combine(TrackRoot, "services", "api", ".env");
    public static readonly string SourceDir = Path.Combine(TrackRoot, "hosted", "support-explainer");

    // Shared with the API so the hosted agent cannot drift from the prompt
    // blocks and determination policy the coordinator uses. Dependency-free,
    // so they bundle cleanly.
    //
    // This is a build-time snapshot, not a live dependency: a deployed agent
    // keeps the policy it shipped with until it is published again.
    // Tightening the policy therefore needs a re-publish, or the
    // internet-facing copy stays on the old one.
    public static readonly string ApiDir = Path.Combine(TrackRoot, "services", "api", "AgenticSupportGuide.Api");
    public static readonly string[] SharedSources =
    [
        Path.Combine("Agents", "Shared", "PromptBlocks.cs"),
        Path.Combine("Agents", "Shared", "Determinations.cs"),
        Path.Combine("Parity", "PyText.cs"),
    ];

    // The package versions, from the one place this track pins them.
    private static readonly string[] BuildFiles = ["Directory.Build.props", "Directory.Packages.props"];

    private const string AgentDir = "support-explainer";
    private const string AgentNamePrefix = "asg-hosted-explainer-";

    // Fixed file timestamp, so identical sources zip identically. 1980-01-01
    // is the earliest the zip format can represent.
    private static readonly DateTime ZipEpoch = new(1980, 1, 1, 0, 0, 0, DateTimeKind.Utc);

    // Verified against Azure.AI.Projects.Agents 3.0.0-beta.5. Changing these is
    // what breaks a deploy most often, so they are named constants, not inline
    // literals.
    private const string Runtime = "dotnet_10";
    private static readonly string[] EntryPoint = ["dotnet", "SupportExplainer.dll"];
    private const string Protocol = "responses";
    private const string ProtocolVersion = "2.0.0";
    private const string Cpu = "1";
    private const string Memory = "2Gi";

    private const int PollIntervalSeconds = 10;
    private const int PollTimeoutSeconds = 900;

    private static readonly HashSet<string> Healthy = ["succeeded", "running", "active", "ready"];

    public static async Task<int> MainAsync(string[] args)
    {
        // Must precede parsing: the --suffix default reads the environment.
        LoadEnv();

        var apply = new Option<bool>("--apply") { Description = "Upload and build." };
        var status = new Option<bool>("--status") { Description = "Show version states." };
        var delete = new Option<bool>("--delete") { Description = "Delete this agent." };
        var rollback = new Option<string?>("--rollback") { Description = "Pin 100% of traffic to this version instead of @latest.", HelpName = "VERSION" };
        var suffixOption = new Option<string>("--suffix")
        {
            Description = "Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
            DefaultValueFactory = _ => Environment.GetEnvironmentVariable("WORKSHOP_LEARNER_SUFFIX") ?? "",
        };
        var command = new RootCommand("Deploy the Support Explainer to Foundry as a hosted agent.") { apply, status, delete, rollback, suffixOption };
        command.SetAction(async (parsed, cancellationToken) =>
        {
            var suffix = PyText.Lower(PyText.Strip(parsed.GetValue(suffixOption) ?? ""));
            if (suffix.Length == 0)
            {
                Console.Error.WriteLine("A learner suffix is required. Pass --suffix <your-alias> or set WORKSHOP_LEARNER_SUFFIX.");
                return 2;
            }
            if (!SuffixRe().IsMatch(suffix))
            {
                Console.Error.WriteLine($"Invalid suffix {PyText.Repr(suffix)}. Use 1-24 chars of a-z, 0-9 or '-'.");
                return 2;
            }
            if (parsed.GetValue(delete))
            {
                return await DeleteAsync(suffix);
            }
            if (parsed.GetValue(rollback) is { Length: > 0 } target)
            {
                return await RollbackAsync(suffix, target);
            }
            if (parsed.GetValue(status))
            {
                return await StatusAsync(suffix);
            }
            return await PublishAsync(suffix, parsed.GetValue(apply));
        });
        // No @file response files: "--rollback @latest" means the alias, as it does to argparse.
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    public static string AgentName(string suffix) => $"{AgentNamePrefix}{suffix}";

    /// <summary>
    /// Stage the upload: a flat folder, because Foundry restores and publishes
    /// the project at the root of the zip and runs `dotnet SupportExplainer.dll`.
    /// </summary>
    public static List<string> Stage(string into)
    {
        var assets = PromptEnvelope.LoadAgentAssets(AgentDir);
        var instructions = PromptEnvelope.ComposeInstructions(
            assets.AgentMdBody,
            assets.AgentMdFrontmatter,
            PromptEnvelope.DeclaredResponseFormat(assets.Manifest));

        Directory.CreateDirectory(into);
        var names = new List<string>();
        void Add(string name, string body)
        {
            var path = Path.Combine(into, name);
            File.WriteAllText(path, body, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            // The SDK stamps each entry with the file's time, so the same
            // sources would otherwise produce a different sha256 on every run.
            // Module 5 has learners compare that hash across runs, so pin it.
            File.SetLastWriteTimeUtc(path, ZipEpoch);
            names.Add(name);
        }

        foreach (var path in Directory.GetFiles(SourceDir).Order(StringComparer.Ordinal))
        {
            var name = Path.GetFileName(path);
            if (name != "instructions.md")
            {
                Add(name, File.ReadAllText(path));
            }
        }
        // Generated, not committed: the hosted agent and the prompt agent must
        // never drift from the same agent.md.
        Add("instructions.md", instructions);
        foreach (var shared in SharedSources)
        {
            Add(Path.GetFileName(shared), File.ReadAllText(Path.Combine(ApiDir, shared)));
        }
        foreach (var name in BuildFiles)
        {
            Add(name, File.ReadAllText(Path.Combine(TrackRoot, name)));
        }
        return names;
    }

    /// <summary>The zip the SDK would upload, its sha256 and its entries, without uploading it.</summary>
    /// <remarks>
    /// The .NET SDK zips a folder itself rather than taking a zip. So the dry
    /// run hands the staged folder to the same SDK call over a transport that
    /// records the request and answers locally: what is printed is exactly
    /// what --apply sends, and nothing leaves this process.
    /// </remarks>
    public static async Task<(byte[] Zip, string Sha256, List<string> Names)> BuildZipAsync()
    {
        var root = Directory.CreateTempSubdirectory("asg-hosted-");
        try
        {
            var staged = Path.Combine(root.FullName, "code");
            Stage(staged);
            var capture = new CaptureUpload();
            var client = new AgentAdministrationClient(
                new Uri("https://dry-run.invalid/api/projects/dry-run"),
                new DryRunToken(),
                new AgentAdministrationClientOptions { Transport = new HttpClientPipelineTransport(new HttpClient(capture)) });
            await client.CreateAgentVersionFromCodeAsync(AgentName("dry-run"), staged, new AgentVersionFromCodeMetadata(Definition("", "")));
            var zip = capture.Zip ?? throw new InvalidOperationException("The SDK sent no code part.");
            using var archive = new ZipArchive(new MemoryStream(zip));
            return (zip, Convert.ToHexStringLower(SHA256.HashData(zip)), [.. archive.Entries.Select(entry => entry.FullName)]);
        }
        finally
        {
            root.Delete(recursive: true);
        }
    }

    private static HostedAgentDefinition Definition(string modelDeployment, string endpoint)
    {
        var definition = new HostedAgentDefinition(cpu: Cpu, memory: Memory)
        {
            Versions = { new ProtocolVersionRecord(new ProjectsAgentProtocol(Protocol), ProtocolVersion) },
            CodeConfiguration = new CodeConfiguration(
                runtime: Runtime,
                entryPoint: EntryPoint,
                // Foundry restores and publishes the project during the image build.
                dependencyResolution: CodeDependencyResolution.RemoteBuild),
        };
        definition.EnvironmentVariables["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"] = endpoint;
        definition.EnvironmentVariables["FOUNDRY_MODEL_DEPLOYMENT"] = modelDeployment;
        return definition;
    }

    private static AgentAdministrationClient Client(string endpoint) => new(new Uri(endpoint), Credentials.Default());

    /// <summary>Return (state, detail).</summary>
    /// <remarks>
    /// <c>status</c> is the build/version outcome and must win. List responses
    /// also carry a <c>state</c> field describing the *agent*, which stays
    /// "active" even when the version failed to build - reading that first
    /// reports a broken deploy as a good one. The SDK's typed version has no
    /// error at all, so this reads the response itself.
    /// </remarks>
    private static (string State, string Detail) VersionState(JsonElement version)
    {
        var state = "unknown";
        foreach (var field in (ReadOnlySpan<string>)["status", "state", "provisioning_state"])
        {
            if (version.TryGetProperty(field, out var value) && value.ValueKind == JsonValueKind.String && value.GetString() is { Length: > 0 } text)
            {
                state = text;
                break;
            }
        }
        var detail = "";
        if (version.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.Object)
        {
            var code = error.TryGetProperty("code", out var c) && c.GetString() is { Length: > 0 } codeText ? codeText : "?";
            var message = error.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
            detail = $"{code}: {message}";
        }
        return (PyText.Lower(state), detail);
    }

    private static async Task<(string State, string Detail)> GetVersionStateAsync(AgentAdministrationClient client, string agentName, string versionId)
    {
        var result = await client.GetAgentVersionAsync(agentName, versionId, new RequestOptions());
        using var document = JsonDocument.Parse(result.GetRawResponse().Content);
        return VersionState(document.RootElement);
    }

    private static async Task<int> PollAsync(AgentAdministrationClient client, string agentName, string versionId)
    {
        var started = Stopwatch.StartNew();
        var last = "";
        while (started.Elapsed.TotalSeconds < PollTimeoutSeconds)
        {
            var (state, detail) = await GetVersionStateAsync(client, agentName, versionId);
            var elapsed = (int)started.Elapsed.TotalSeconds;
            if (state != last)
            {
                Console.WriteLine($"  [{elapsed,4}s] {state}{(detail.Length > 0 ? " - " + detail : "")}");
                last = state;
            }
            if (Healthy.Contains(state))
            {
                Console.WriteLine($"\nBuild finished in {elapsed}s. Agent is {state}.");
                return 0;
            }
            if (state is "failed" or "canceled" or "cancelled")
            {
                Console.Error.WriteLine($"\nBuild {state} after {elapsed}s.");
                if (detail.Length > 0)
                {
                    Console.Error.WriteLine($"  {detail}");
                }
                Console.Error.WriteLine("  Inspect logs in the Foundry portal under Agents -> this agent.");
                return 1;
            }
            await Task.Delay(TimeSpan.FromSeconds(PollIntervalSeconds));
        }
        Console.WriteLine($"\nStill building after {PollTimeoutSeconds}s. Re-check with --status.");
        return 1;
    }

    private static async Task<int> PublishAsync(string suffix, bool apply)
    {
        var endpoint = Endpoint();
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.");
            return 2;
        }
        var model = Environment.GetEnvironmentVariable("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER") ?? "";
        if (model.Length == 0)
        {
            Console.Error.WriteLine("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER is not set.");
            return 2;
        }

        var agentName = AgentName(suffix);
        var (zip, digest, names) = await BuildZipAsync();

        Console.WriteLine($"Agent name : {agentName}");
        Console.WriteLine($"Runtime    : {Runtime}");
        Console.WriteLine($"Entrypoint : {string.Join(' ', EntryPoint)}");
        Console.WriteLine($"Protocol   : {Protocol} v{ProtocolVersion}");
        Console.WriteLine($"Resources  : cpu={Cpu} memory={Memory}");
        Console.WriteLine($"Zip        : {zip.Length.ToString("N0", CultureInfo.InvariantCulture)} bytes, sha256={digest[..16]}...");
        foreach (var name in names)
        {
            Console.WriteLine($"             {name}");
        }

        if (!apply)
        {
            Console.WriteLine("\nDry run. Nothing uploaded. Re-run with --apply to deploy.");
            return 0;
        }

        var client = Client(endpoint);
        var root = Directory.CreateTempSubdirectory("asg-hosted-");
        try
        {
            var staged = Path.Combine(root.FullName, "code");
            Stage(staged);

            Console.WriteLine("\nUploading and starting remote build...");
            var started = Stopwatch.StartNew();
            var version = (await client.CreateAgentVersionFromCodeAsync(agentName, staged, new AgentVersionFromCodeMetadata(Definition(model, endpoint)))).Value;
            var versionId = version.Version ?? "";
            Console.WriteLine($"Upload took {(int)started.Elapsed.TotalSeconds}s. Version: {versionId}");
            if (versionId.Length == 0)
            {
                Console.Error.WriteLine("No version id returned by CreateAgentVersionFromCode; cannot poll.");
                return 1;
            }
            return await PollAsync(client, agentName, versionId);
        }
        finally
        {
            root.Delete(recursive: true);
        }
    }

    private static (int Number, string Raw) VersionSortKey(string raw) =>
        int.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out var number) ? (number, raw) : (-1, raw);

    private static async Task<int> StatusAsync(string suffix)
    {
        var endpoint = Endpoint();
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.");
            return 2;
        }
        var client = Client(endpoint);
        var agentName = AgentName(suffix);
        var versions = new List<string>();
        await foreach (var listed in client.GetAgentVersionsAsync(agentName))
        {
            versions.Add(listed.Version ?? "");
        }
        if (versions.Count == 0)
        {
            Console.Error.WriteLine($"No versions for {agentName}.");
            return 1;
        }
        // Sorted explicitly rather than trusting list order: this module exists
        // to teach that the versions list cannot be trusted about state, so do
        // not trust it about ordering either.
        versions = [.. versions.OrderByDescending(VersionSortKey)];
        Console.WriteLine($"{versions.Count} version(s) of {agentName}:");
        var latestState = "";
        foreach (var listed in versions)
        {
            var versionId = listed.Length > 0 ? listed : "?";
            // The versions list reports status="active" even for versions that
            // failed to build, and omits `error`. Only a single version's GET
            // tells the truth.
            var (state, detail) = await GetVersionStateAsync(client, agentName, versionId);
            if (latestState.Length == 0)
            {
                latestState = state;
            }
            Console.WriteLine($"  v{versionId}: {state}{(detail.Length > 0 ? " - " + detail : "")}");
        }
        // Exit on the newest version so CI reflects what traffic actually hits.
        return Healthy.Contains(latestState) ? 0 : 1;
    }

    /// <summary>Point 100% of traffic at a specific version instead of @latest.</summary>
    private static async Task<int> RollbackAsync(string suffix, string target)
    {
        var endpoint = Endpoint();
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.");
            return 2;
        }
        var client = Client(endpoint);
        var agentName = AgentName(suffix);

        // Rolling back onto a version that never built is the one mistake this
        // command must not let you make quietly.
        var (state, detail) = await GetVersionStateAsync(client, agentName, target);
        if (!Healthy.Contains(state))
        {
            Console.Error.WriteLine($"v{target} is '{state}'{(detail.Length > 0 ? " - " + detail : "")}; refusing to send traffic to it.");
            return 1;
        }

        await client.PatchAgentAsync(agentName, new PatchAgentOptions
        {
            AgentEndpoint = new AgentEndpointConfiguration
            {
                VersionSelector = new VersionSelector([new FixedRatioVersionSelectionRule(target, 100)]),
            },
        });
        Console.WriteLine($"{agentName}: 100% of traffic now pinned to v{target}.");
        return 0;
    }

    private static async Task<int> DeleteAsync(string suffix)
    {
        var endpoint = Endpoint();
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.");
            return 2;
        }
        var client = Client(endpoint);
        var agentName = AgentName(suffix);
        var present = new HashSet<string>();
        await foreach (var agent in client.GetAgentsAsync())
        {
            present.Add(agent.Name ?? "");
        }
        if (!present.Contains(agentName))
        {
            Console.WriteLine($"{agentName} not found. Nothing to delete.");
            return 0;
        }
        // Playground or invocation sessions block deletion until they expire.
        await client.DeleteAgentAsync(agentName, force: true);
        Console.WriteLine($"deleted {agentName}");
        return 0;
    }

    private static string Endpoint() =>
        Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") is { Length: > 0 } project
            ? project
            : Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_ENDPOINT") ?? "";

    private static void LoadEnv()
    {
        if (!File.Exists(EnvFile))
        {
            return;
        }
        foreach (var raw in PyText.SplitLines(File.ReadAllText(EnvFile)))
        {
            var line = PyText.Strip(raw);
            if (line.Length > 0 && !line.StartsWith('#') && line.Contains('='))
            {
                var at = line.IndexOf('=');
                var key = PyText.Strip(line[..at]);
                if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(key)))
                {
                    Environment.SetEnvironmentVariable(key, PyText.Strip(line[(at + 1)..]));
                }
            }
        }
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;

    [GeneratedRegex(@"^[a-z0-9-]{1,24}\z", RegexOptions.CultureInvariant)]
    private static partial Regex SuffixRe();

    /// <summary>Records the upload and answers it locally, so a dry run sends nothing.</summary>
    private sealed class CaptureUpload : HttpMessageHandler
    {
        public byte[]? Zip { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var boundary = request.Content!.Headers.ContentType!.Parameters.Single(p => p.Name == "boundary").Value!.Trim('"');
            Zip = CodePart(await request.Content.ReadAsByteArrayAsync(cancellationToken), boundary);
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"object":"agent.version","id":"dry-run:0","name":"dry-run","version":"0","created_at":0,"status":"creating","definition":{"kind":"hosted","cpu":"1","memory":"2Gi"}}""",
                    Encoding.UTF8,
                    "application/json"),
            };
        }

        /// <summary>The body of the multipart part named <c>code</c>.</summary>
        private static byte[] CodePart(byte[] body, string boundary)
        {
            var delimiter = Encoding.ASCII.GetBytes("--" + boundary);
            var rest = body.AsSpan();
            while (rest.IndexOf(delimiter) is var at and >= 0)
            {
                rest = rest[(at + delimiter.Length)..];
                var next = rest.IndexOf(delimiter);
                if (next < 0)
                {
                    break;
                }
                var part = rest[..next];
                var headersEnd = part.IndexOf("\r\n\r\n"u8);
                if (headersEnd >= 0 && Encoding.ASCII.GetString(part[..headersEnd]).Contains("name=code", StringComparison.Ordinal))
                {
                    // The part ends with the CRLF that precedes the next delimiter.
                    return part[(headersEnd + 4)..^2].ToArray();
                }
            }
            throw new InvalidOperationException("The upload carried no code part.");
        }
    }

    /// <summary>A token that is never sent anywhere: the dry-run transport answers locally.</summary>
    private sealed class DryRunToken : AuthenticationTokenProvider
    {
        public override GetTokenOptions? CreateTokenOptions(IReadOnlyDictionary<string, object> properties) => new(properties);

        public override AuthenticationToken GetToken(GetTokenOptions options, CancellationToken cancellationToken) =>
            new("dry-run", "Bearer", DateTimeOffset.UtcNow.AddHours(1));

        public override ValueTask<AuthenticationToken> GetTokenAsync(GetTokenOptions options, CancellationToken cancellationToken) =>
            ValueTask.FromResult(GetToken(options, cancellationToken));
    }
}
