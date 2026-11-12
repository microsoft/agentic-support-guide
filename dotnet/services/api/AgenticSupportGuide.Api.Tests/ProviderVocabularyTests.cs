using System.Text;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Cross-language guard against stale provider/binding vocabulary.</summary>
/// <remarks>
/// The provider id is a C# constant, but it is also written into YAML
/// manifests, TypeScript, PowerShell, and Markdown, none of which can import it.
/// This test greps those files so a rename cannot silently go half-done.
///
/// The globs that name the Python track's folders name this track's instead:
/// <c>python/scripts/*.py</c> is <c>dotnet/scripts/*.cs</c>, and the app's
/// <c>*.py</c> source is the API project's <c>*.cs</c> source. The shared
/// folders are scanned exactly as the Python test scans them.
/// </remarks>
public sealed class ProviderVocabularyTests
{
    private static readonly string RepoRoot = Conformance.Goldens.RepoRoot;

    // Vocabulary from the retired persisted-Assistants design.
    private static readonly string[] StaleTerms =
    [
        "azure_foundry_agents",
        "foundry_agents_bound",
        "agent-bindings.local.json",
        "agent-bindings.example.json",
        "sync_foundry_agents",
        "FoundryRemoteAgentAdapter",
        "FoundryAgentClient",
        "sdk_client",
        "remote assistant",
        "--rebind",
    ];

    private static readonly string[] ScanGlobs =
    [
        "agents/**/*.yaml",
        "agents/**/*.md",
        "apps/web/src/**/*.ts",
        "apps/web/src/**/*.tsx",
        "dotnet/scripts/*.ps1",
        "dotnet/scripts/*.cs",
        "maintenance/*.ps1",
        "maintenance/*.py",
        "dotnet/services/api/AgenticSupportGuide.Api/**/*.cs",
        "*.md",
        "docs/**/*.md",
        "dotnet/infra/*.md",
        "evals/*.md",
        ".github/workflows/*.yml",
    ];

    // The Python list, plus this track's build output.
    private static readonly HashSet<string> ExcludeParts = ["node_modules", ".venv", "__pycache__", "dist", "bin", "obj"];

    // ADRs are immutable historical records: 0001/0002 legitimately describe the
    // superseded persisted-agent design. A new ADR supersedes them instead.
    private static readonly string[] ExcludeDirs = ["docs/adr"];

    public static TheoryData<string> StaleTermCases() => [.. StaleTerms];

    private static List<string> ScannedFiles()
    {
        var seen = new List<string>();
        var unique = new HashSet<string>(StringComparer.Ordinal);
        foreach (var pattern in ScanGlobs)
        {
            foreach (var path in Glob(pattern))
            {
                var parts = Path.GetRelativePath(RepoRoot, path).Split(Path.DirectorySeparatorChar);
                if (parts.Any(ExcludeParts.Contains))
                {
                    continue;
                }
                var rel = string.Join('/', parts);
                if (ExcludeDirs.Any(d => rel.StartsWith(d, StringComparison.Ordinal)))
                {
                    continue;
                }
                if (unique.Add(path))
                {
                    seen.Add(path);
                }
            }
        }
        return seen;
    }

    /// <summary><c>REPO_ROOT.glob(pattern)</c> for the two shapes used here: <c>dir/*.ext</c> and <c>dir/**/*.ext</c>.</summary>
    private static IEnumerable<string> Glob(string pattern)
    {
        var recursive = pattern.Contains("/**/", StringComparison.Ordinal);
        var parts = pattern.Replace("/**/", "/", StringComparison.Ordinal).Split('/');
        var directory = Path.Combine([RepoRoot, .. parts[..^1]]);
        return Directory.Exists(directory)
            ? Directory.EnumerateFiles(directory, parts[^1], recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly)
            : [];
    }

    [Theory]
    [MemberData(nameof(StaleTermCases))]
    public void No_stale_persisted_agent_vocabulary(string term)
    {
        var offenders = ScannedFiles()
            .Where(path => File.ReadAllText(path, Encoding.UTF8).Contains(term, StringComparison.Ordinal))
            .Select(path => Path.GetRelativePath(RepoRoot, path))
            .ToList();
        Assert.True(offenders.Count == 0, $"stale term {PyText.Repr(term)} still present in {PyText.ReprList(offenders)}");
    }

    [Fact]
    public void Provider_id_is_the_expected_value()
    {
        Assert.Equal("azure_foundry_responses", MafAgentRuntime.ProviderId);
    }
}
