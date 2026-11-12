#!/usr/bin/env dotnet
// Render the workshop sample workflows to Mermaid.
//
//     dotnet run dotnet/scripts/render_workflow_diagram.cs                # print
//     dotnet run dotnet/scripts/render_workflow_diagram.cs -- --write     # update the docs
//     dotnet run dotnet/scripts/render_workflow_diagram.cs -- --dot       # app graph as DOT
//
// Uses `WorkflowVisualizer`, so the diagram is generated from the workflow
// that actually runs rather than drawn by hand. The .NET tests fail if the
// committed diagram and the built workflow disagree.
//
// https://learn.microsoft.com/agent-framework/workflows/visualization

#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine
#:include ../../workshop/dotnet/code/05_first_workflow.cs
#:include ../../workshop/dotnet/code/07_conditional_repair.cs
// The samples are programs too; INCLUDED leaves out the part that runs them.
#:property DefineConstants=$(DefineConstants);INCLUDED
// Both samples include _shared.cs, so it arrives twice; once is enough.
#:property NoWarn=$(NoWarn);CS2002

using System.CommandLine;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.Workflows;
using Microsoft.Agents.AI.Workflows;

// The tests compile this file too, and call its methods directly.
#if !UNDER_TEST
return await RenderWorkflowDiagram.MainAsync(args);
#endif

public static class RenderWorkflowDiagram
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string RepoRoot = Path.GetFullPath(Path.Combine(TrackRoot, ".."));

    // (builder key, marker used in the markdown, file the diagram lives in)
    public static readonly (string Key, string Marker, string Path)[] Diagrams =
    [
        ("05_first_workflow", "sample-05", Path.Combine(RepoRoot, "workshop", "dotnet", "module-3-workflows.md")),
        ("07_conditional_repair", "sample-07", Path.Combine(RepoRoot, "workshop", "dotnet", "module-3-workflows.md")),
        ("app", "app-workflow", Path.Combine(RepoRoot, "docs", "orchestration-patterns.md")),
    ];

    public static async Task<int> MainAsync(string[] args)
    {
        var write = new Option<bool>("--write") { Description = "Update the docs in place." };
        var dot = new Option<bool>("--dot") { Description = "Print the app graph as Graphviz DOT and exit." };
        var command = new RootCommand("Render the workshop sample workflows to Mermaid.") { write, dot };
        command.SetAction(parsed => Run(parsed.GetValue(write), parsed.GetValue(dot)));
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    private static int Run(bool write, bool dot)
    {
        if (dot)
        {
            Console.WriteLine(AppDot());
            return 0;
        }

        var changed = 0;
        var problems = 0;
        foreach (var (key, marker, path) in Diagrams)
        {
            var mermaid = Render(key);
            if (!write)
            {
                Console.WriteLine($"--- {key} -> {Path.GetFileName(path)} ({marker}) ---");
                Console.WriteLine(mermaid);
                Console.WriteLine();
                continue;
            }
            try
            {
                if (Write(path, marker, mermaid))
                {
                    changed++;
                    Console.WriteLine($"  updated {Path.GetFileName(path)} ({marker})");
                }
            }
            catch (Exception exc) when (exc is IOException or ArgumentException)
            {
                problems++;
                Console.Error.WriteLine($"  [fail] {exc.Message}");
            }
        }

        if (write)
        {
            Console.WriteLine($"\n{changed} diagram(s) updated.");
        }
        return problems > 0 ? 1 : 0;
    }

    /// <summary>The application's own graph, built exactly as a request builds it.</summary>
    /// <remarks>
    /// The runtime and retriever are only touched when the workflow *runs*;
    /// building it just stores them on the nodes. So a diagram needs no Azure,
    /// and it is still the real topology -- the same BuildPlanWorkflow the API
    /// calls, with the same nodes and the same edge conditions.
    /// </remarks>
    private static Workflow AppWorkflow()
    {
        var request = new CoordinatorRequest(
            DealerGroupId: "GROUP-A",
            DealershipLabel: "",
            RegionId: "",
            Segment: "",
            ProcessScore: 0,
            AppointmentAttendanceRate: 0.0,
            FollowupIndex: 0.0,
            EngagementIndex: 0.0,
            AreaSeries: null!,
            OperationsSeries: null!,
            Category: "lead-response",
            ConcernText: "",
            AllowedResources: [],
            AllowedGoalIds: [],
            AllowedStrategyIds: []);
        var context = new RunContext(CorrelationId: "diagram", DealerGroupId: "GROUP-A", ProviderModel: "");
        return Graph.BuildPlanWorkflow(request, context, runtime: null!, evidenceRetriever: new FixtureEvidenceRetriever(), providerDisplay: "");
    }

    public static string Render(string key) => (key switch
    {
        "app" => AppWorkflow(),
        "05_first_workflow" => FirstWorkflow.BuildWorkflow(),
        "07_conditional_repair" => ConditionalRepair.BuildWorkflow(),
        _ => throw new ArgumentOutOfRangeException(nameof(key), key, "no such diagram"),
    }).ToMermaidString().Trim();

    private static string Block(string marker, string mermaid) =>
        $"<!-- {marker}:start -->\n```mermaid\n{mermaid}\n```\n<!-- {marker}:end -->";

    private static Regex Pattern(string marker) =>
        new($"<!-- {Regex.Escape(marker)}:start -->.*?<!-- {Regex.Escape(marker)}:end -->", RegexOptions.Singleline | RegexOptions.CultureInvariant);

    /// <summary>The app graph in Graphviz DOT, straight from Agent Framework.</summary>
    /// <remarks>
    /// Pipe it through Graphviz `dot -Tsvg` to refresh
    /// apps/web/public/workflow-graph.svg. The SVG is committed because App
    /// Service has no Graphviz.
    /// </remarks>
    public static string AppDot() => AppWorkflow().ToDotString().Trim();

    /// <summary>Exactly one well-formed block, or a hard failure.</summary>
    /// <remarks>
    /// Silently updating the first of several duplicates, or reporting "no
    /// marker" for a block whose end tag is missing, both look like success
    /// and leave the doc wrong.
    /// </remarks>
    private static Match FindBlock(string text, string marker, string path)
    {
        var starts = Count(text, $"<!-- {marker}:start -->");
        var ends = Count(text, $"<!-- {marker}:end -->");
        if (starts != 1 || ends != 1)
        {
            throw new ArgumentException(
                $"{Path.GetFileName(path)}: expected exactly one {marker} start and end marker, found {starts} start and {ends} end");
        }
        var found = Pattern(marker).Match(text);
        if (!found.Success)
        {
            throw new ArgumentException($"{Path.GetFileName(path)}: {marker} end marker appears before its start marker");
        }
        return found;
    }

    /// <summary>The mermaid currently in the doc, or null if the block is absent.</summary>
    public static string? Committed(string path, string marker)
    {
        if (!File.Exists(path))
        {
            return null;
        }
        var text = ReadText(path);
        if (!text.Contains($"<!-- {marker}:start -->", StringComparison.Ordinal))
        {
            return null;
        }
        var body = FindBlock(text, marker, path).Value;
        var fence = Regex.Match(body, "```mermaid\n(.*?)\n```", RegexOptions.Singleline | RegexOptions.CultureInvariant);
        return fence.Success ? fence.Groups[1].Value.Trim() : null;
    }

    /// <summary>Replace the marked block. Returns true if the file changed.</summary>
    public static bool Write(string path, string marker, string mermaid)
    {
        var text = ReadText(path);
        var found = FindBlock(text, marker, path);
        var replaced = text[..found.Index] + Block(marker, mermaid) + text[(found.Index + found.Length)..];
        if (replaced == text)
        {
            return false;
        }
        File.WriteAllText(path, replaced);
        return true;
    }

    // The docs are committed with LF line endings, which is what Python's
    // read_text gives on any platform.
    private static string ReadText(string path) => File.ReadAllText(path).Replace("\r\n", "\n", StringComparison.Ordinal);

    private static int Count(string text, string value)
    {
        var count = 0;
        for (var at = text.IndexOf(value, StringComparison.Ordinal); at >= 0; at = text.IndexOf(value, at + value.Length, StringComparison.Ordinal))
        {
            count++;
        }
        return count;
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;
}
