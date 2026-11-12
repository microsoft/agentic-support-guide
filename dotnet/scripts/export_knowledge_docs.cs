#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Export the dealer group evidence fixtures as documents for Foundry IQ.
//
// Module 6 needs real files in blob storage to index. The in-repo fixtures
// are the same evidence the agents already use, so grounding the agent on
// these exports means the knowledge base and the coordinator see the same
// facts.
//
// Usage:
//   dotnet run dotnet/scripts/export_knowledge_docs.cs
//   dotnet run dotnet/scripts/export_knowledge_docs.cs -- --out evals/knowledge

using System.CommandLine;
using System.Runtime.CompilerServices;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.Evidence;

return await ExportKnowledgeDocs.MainAsync(args);

public static class ExportKnowledgeDocs
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string RepoRoot = Path.GetFullPath(Path.Combine(TrackRoot, ".."));
    private static readonly string DefaultOut = Path.Combine(RepoRoot, "evals", "knowledge");

    public static async Task<int> MainAsync(string[] args)
    {
        var outOption = new Option<string>("--out") { Description = "Output directory.", DefaultValueFactory = _ => DefaultOut };
        var command = new RootCommand("Export the dealer group evidence fixtures as documents for Foundry IQ.") { outOption };
        // Resolved, so the relative form in the usage above works from the repo root.
        command.SetAction((parsed, _) => ExportAsync(Path.GetFullPath(parsed.GetValue(outOption) ?? DefaultOut)));
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    private static async Task<int> ExportAsync(string outDir)
    {
        var retriever = new FixtureEvidenceRetriever();
        Directory.CreateDirectory(outDir);

        var written = 0;
        foreach (var group in FixtureEvidenceRetriever.ListAvailableDealerGroups())
        {
            foreach (var category in MockData.CategoryIds)
            {
                var bundle = await retriever.RetrieveAsync(new EvidenceRequest(group, category, DetectedNeedHint: ""));
                if (bundle.Citations.Count == 0)
                {
                    continue;
                }

                var lines = new List<string>
                {
                    $"# {group} - {category}",
                    "",
                    "Dealer group: " + group,
                    "Category: " + category,
                    "",
                    "> Synthetic data. Nothing here is a pricing, financing, credit,",
                    "> compliance, safety, or staffing determination. A human reviews",
                    "> every recommendation.",
                    "",
                };
                foreach (var c in bundle.Citations)
                {
                    lines.AddRange(
                    [
                        $"## {c.SourceTitle}",
                        "",
                        $"- Citation ID: {c.CitationId}",
                        $"- Dealer group: {c.DealerGroupId}",
                        $"- Source type: {c.SourceType}",
                        $"- Section: {c.SectionOrPage}",
                        "",
                        c.EvidenceSummary,
                        "",
                    ]);
                }

                var path = Path.Combine(outDir, $"{group.ToLowerInvariant()}-{category}.md");
                // Text-mode newlines, as Python writes them: CRLF on Windows.
                await File.WriteAllTextAsync(path, string.Join("\n", lines).Replace("\n", Environment.NewLine, StringComparison.Ordinal));
                written++;
            }
        }

        Console.WriteLine($"Wrote {written} document(s) to {outDir}");
        Console.WriteLine("\nUpload with:");
        Console.WriteLine("  az storage blob upload-batch \\");
        Console.WriteLine("    --account-name <storage-account> \\");
        Console.WriteLine("    --destination group-knowledge \\");
        Console.WriteLine($"    --source {Path.GetRelativePath(RepoRoot, outDir)} \\");
        Console.WriteLine("    --auth-mode login");
        return 0;
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;
}
