using System.Text.Json;
using System.Text.Json.Nodes;
using YamlDotNet.Serialization;

namespace AgenticSupportGuide.Api.Tests.Conformance;

/// <summary>
/// The conformance goldens recorded from the Python track, and the rules for
/// where this track may differ (conformance/allowed_differences.yaml).
/// </summary>
public static class Goldens
{
    public static readonly string RepoRoot = FindRepoRoot();

    public static readonly string Dir = Path.Combine(RepoRoot, "conformance", "goldens");

    /// <summary>Python-track strings and the .NET strings that replace them, longest first.</summary>
    public static readonly IReadOnlyList<(string Python, string DotNet)> TrackSubstitutions = LoadSubstitutions();

    public static IEnumerable<string> ScenarioNames() =>
        Directory.GetFiles(Path.Combine(Dir, "scenarios"), "*.json")
            .Select(Path.GetFileNameWithoutExtension)
            .Order(StringComparer.Ordinal)!;

    public static JsonNode Load(string relativePath) =>
        JsonNode.Parse(File.ReadAllText(Path.Combine(Dir, relativePath)), documentOptions: new JsonDocumentOptions())!;

    public static string LoadText(string relativePath) =>
        File.ReadAllText(Path.Combine(Dir, relativePath)).Replace("\r\n", "\n", StringComparison.Ordinal);

    /// <summary>A golden string as this track would say it.</summary>
    public static string ForThisTrack(string text)
    {
        foreach (var (python, dotnet) in TrackSubstitutions)
        {
            text = text.Replace(python, dotnet, StringComparison.Ordinal);
        }
        return text;
    }

    private static string FindRepoRoot()
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "conformance", "goldens")))
            {
                return dir.FullName;
            }
        }
        throw new DirectoryNotFoundException("conformance/goldens not found above the test output directory.");
    }

    private static List<(string Python, string DotNet)> LoadSubstitutions()
    {
        var yaml = File.ReadAllText(Path.Combine(RepoRoot, "conformance", "allowed_differences.yaml"));
        var root = new DeserializerBuilder().Build().Deserialize<Dictionary<string, object>>(yaml);
        var entries = (List<object>)root["track_substitutions"];
        return entries
            .Cast<Dictionary<object, object>>()
            .Select(e => ((string)e["python"], (string)e["dotnet"]))
            .OrderByDescending(e => e.Item1.Length)
            .ToList();
    }
}
