using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Tests.Conformance;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Guards that the runtime never uses the retired Assistants API.
/// </summary>
/// <remarks>
/// <para>
/// Legacy <c>asst_*</c> assistants are what triggered the Foundry portal's
/// "Update your agents" migration banner. Prompt agents published through
/// <c>AgentAdministrationClient.CreateAgentVersion</c> are Foundry's current
/// model and are fine - they render natively in the portal with no banner.
/// </para>
/// <para>
/// So this guard bans the legacy path, not agent publishing.
/// </para>
/// </remarks>
public sealed class NoPersistedAgentsTests
{
    private static readonly string[] ScanRoots =
    [
        Path.Combine(Goldens.RepoRoot, "dotnet", "services", "api", "AgenticSupportGuide.Api"),
        Path.Combine(Goldens.RepoRoot, "dotnet", "scripts"),
    ];

    // Retired Assistants-API surface: the persistent agents client and its package.
    public static readonly TheoryData<string> ForbiddenSymbols = new("PersistentAgentsClient", "Azure.AI.Agents.Persistent");

    // Assistants CRUD, which lives on the persistent client's Administration
    // property. The current agent API has a DeleteAgent of its own on
    // AgentAdministrationClient, so the legacy calls are matched by that path.
    // `CreateAgentVersion` is deliberately absent: that is the current
    // prompt-agent API.
    public static readonly TheoryData<string> ForbiddenCalls = new(
        ".Administration.CreateAgent",
        ".Administration.UpdateAgent",
        ".Administration.DeleteAgent");

    // Publishing prompt agents is allowed only from this script, so the runtime
    // request path can never accidentally create a resource.
    private static readonly HashSet<string> PublishAllowlist = ["dotnet/scripts/publish_prompt_agents.cs"];

    // Patterns, because the .NET client has both a synchronous and an `Async`
    // form of each call.
    public static readonly TheoryData<string> PublishSymbols = new(@"\bToPromptAgent", @"\bCreateAgentVersion(Async)?\(");

    private static List<string> CSharpFiles()
    {
        var files = new List<string>();
        foreach (var root in ScanRoots)
        {
            if (!Directory.Exists(root))
            {
                continue;
            }
            files.AddRange(Directory
                .EnumerateFiles(root, "*.cs", SearchOption.AllDirectories)
                .Where(path => !Path.GetRelativePath(root, path).Split(Path.DirectorySeparatorChar).Any(part => part is "bin" or "obj")));
        }
        return files;
    }

    private static string Relative(string path) => Path.GetRelativePath(Goldens.RepoRoot, path).Replace('\\', '/');

    /// <summary>Lines excluding comments, so prose naming these symbols doesn't trip the guard.</summary>
    private static List<string> CodeLines(string path)
    {
        var output = new List<string>();
        var inBlock = false;
        foreach (var raw in File.ReadAllLines(path))
        {
            var line = raw.Trim();
            if (inBlock)
            {
                if (line.Contains("*/", StringComparison.Ordinal))
                {
                    inBlock = false;
                }
                continue;
            }
            if (line.StartsWith("/*", StringComparison.Ordinal))
            {
                if (line.IndexOf("*/", 2, StringComparison.Ordinal) < 0)
                {
                    inBlock = true;
                }
                continue;
            }
            if (line.StartsWith("//", StringComparison.Ordinal))
            {
                continue;
            }
            output.Add(line);
        }
        return output;
    }

    [Theory]
    [MemberData(nameof(ForbiddenSymbols))]
    public void Legacy_assistants_api_is_never_imported(string symbol)
    {
        var pattern = new Regex($@"\b{Regex.Escape(symbol)}\b");
        var offenders = CSharpFiles()
            .Where(path => CodeLines(path).Any(pattern.IsMatch))
            .Select(Relative)
            .ToList();
        Assert.True(offenders.Count == 0, $"{symbol} is the retired Assistants API; found in [{string.Join(", ", offenders)}]");
    }

    [Theory]
    [MemberData(nameof(ForbiddenCalls))]
    public void Assistants_crud_calls_are_absent(string call)
    {
        var offenders = CSharpFiles()
            .Where(path => CodeLines(path).Any(line => line.Contains(call, StringComparison.Ordinal)))
            .Select(Relative)
            .ToList();
        Assert.True(offenders.Count == 0, $"{call} is Assistants-API CRUD; found in [{string.Join(", ", offenders)}]");
    }

    /// <summary>Publishing is a GenAIOps step, never something a web request triggers.</summary>
    [Theory]
    [MemberData(nameof(PublishSymbols))]
    public void Agent_publishing_stays_out_of_the_request_path(string symbol)
    {
        var pattern = new Regex(symbol);
        var offenders = CSharpFiles()
            .Select(path => (Path: path, Rel: Relative(path)))
            .Where(file => !PublishAllowlist.Contains(file.Rel) && CodeLines(file.Path).Any(pattern.IsMatch))
            .Select(file => file.Rel)
            .ToList();
        Assert.True(offenders.Count == 0, $"{symbol} may only be used by the publish script; found in [{string.Join(", ", offenders)}]");
    }
}
