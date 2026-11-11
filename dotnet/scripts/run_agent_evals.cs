#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Module 9: grade the agents instead of guessing whether they are good.
//
// The validator's deterministic checks answer "is the output structurally
// valid and safe?". That is necessary but it cannot tell you whether an answer
// is actually grounded in the evidence or actually addresses the question.
// This script answers that, using Foundry's built-in graders via Microsoft
// Agent Framework.
//
// The judge is a separate model deployment from the agents' own model, so
// grading load never starves the agents and learners can see that the grader
// is a different model from the thing being graded.
//
// Usage:
//   dotnet run dotnet/scripts/run_agent_evals.cs -- --list-evaluators
//   dotnet run dotnet/scripts/run_agent_evals.cs -- --dry-run
//   dotnet run dotnet/scripts/run_agent_evals.cs -- --apply

using System.CommandLine;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;
using Azure.AI.Projects;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Foundry;
using Microsoft.Extensions.AI;

return await RunAgentEvals.MainAsync(args);

public static class RunAgentEvals
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string RepoRoot = Path.GetFullPath(Path.Combine(TrackRoot, ".."));
    private static readonly string CasesPath = Path.Combine(RepoRoot, "evals", "synthetic_cases.jsonl");
    private static readonly string EnvFile = Path.Combine(TrackRoot, "services", "api", ".env");

    // Graders that make sense for a grounded, single-turn advisory agent.
    // Groundedness needs `context`; relevance and coherence do not.
    private static readonly string[] DefaultEvaluators = ["groundedness", "relevance", "coherence"];

    // A grade below this on a 1-5 scale is treated as a regression.
    private const double PassThreshold = 3.0;

    public static async Task<int> MainAsync(string[] args)
    {
        var apply = new Option<bool>("--apply") { Description = "Actually call Azure and grade." };
        var dryRun = new Option<bool>("--dry-run") { Description = "Show what would be graded, call nothing. Default." };
        var listEvaluators = new Option<bool>("--list-evaluators") { Description = "List built-in graders and exit." };
        var evaluators = new Option<string>("--evaluators")
        {
            Description = $"Comma-separated grader names. Default: {string.Join(',', DefaultEvaluators)}",
            DefaultValueFactory = _ => string.Join(',', DefaultEvaluators),
        };
        var command = new RootCommand("Module 9: grade the agents instead of guessing whether they are good.") { apply, dryRun, listEvaluators, evaluators };
        command.Validators.Add(result =>
        {
            if (result.GetValue(apply) && result.GetValue(dryRun))
            {
                result.AddError("argument --dry-run: not allowed with argument --apply");
            }
        });
        command.SetAction(async (parsed, _) =>
        {
            LoadEnv();
            if (parsed.GetValue(listEvaluators))
            {
                return ListEvaluators();
            }
            string[] names = [.. (parsed.GetValue(evaluators) ?? "").Split(',').Select(PyText.Strip).Where(n => n.Length > 0)];
            return await RunAsync(names, parsed.GetValue(apply));
        });
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    private static List<JsonElement> LoadCases() =>
        [.. PyText.SplitLines(File.ReadAllText(CasesPath))
            .Where(line => PyText.Strip(line).Length > 0)
            .Select(line => JsonDocument.Parse(line).RootElement.Clone())];

    /// <summary>Groundedness is scored against this text, so it must be the real evidence.</summary>
    private static async Task<string> BuildContextAsync(JsonElement testCase)
    {
        var bundle = await new FixtureEvidenceRetriever().RetrieveAsync(
            new EvidenceRequest(testCase.GetProperty("dealer_group_id").GetString()!, testCase.GetProperty("category").GetString()!, DetectedNeedHint: ""));
        return string.Join("\n", bundle.Citations.Select(c => $"[{c.CitationId}] {c.SourceTitle} ({c.SectionOrPage}): {c.EvidenceSummary}"));
    }

    // The graders FoundryEvals names, keyed as Python's agent framework spells them.
    private static SortedDictionary<string, string> BuiltInEvaluators() =>
        new(typeof(FoundryEvals)
                .GetFields(BindingFlags.Public | BindingFlags.Static)
                .Where(field => field.IsLiteral && field.FieldType == typeof(string))
                .Select(field => (string)field.GetRawConstantValue()!)
                .ToDictionary(value => value, value => value),
            StringComparer.Ordinal);

    private static string[] ResolveEvaluators(IEnumerable<string> names)
    {
        var known = BuiltInEvaluators();
        var resolved = new List<string>();
        foreach (var name in names)
        {
            if (!known.TryGetValue(PyText.Lower(name), out var constant))
            {
                throw new UnknownEvaluatorException($"Unknown evaluator '{name}'. Run --list-evaluators to see valid names.");
            }
            resolved.Add(constant);
        }
        return [.. resolved];
    }

    private static int ListEvaluators()
    {
        var names = BuiltInEvaluators().Keys;
        Console.WriteLine($"{names.Count} built-in Foundry evaluators:");
        foreach (var name in names)
        {
            var marker = DefaultEvaluators.Contains(name) ? "  <- default" : "";
            Console.WriteLine($"  {name}{marker}");
        }
        return 0;
    }

    /// <summary>The fenced block matches what the runtime envelope tells the agent to trust.</summary>
    private static string GroundedPrompt(string query, string context) =>
        $"<<<UNTRUSTED_DATA>>>\n{context}\n<<<END_UNTRUSTED_DATA>>>\n\n{query}";

    /// <summary>Returns the number of cases that regressed.</summary>
    private static async Task<int> GradeAllAsync(
        string endpoint, string agentModel, string judgeModel, string[] evaluatorNames, List<JsonElement> cases, List<string> queries, List<string> contexts)
    {
        var definition = RoleDefinitions.LoadAgentDefinitions(RoleDefinitions.WorkshopAgentDirs)["support-explainer-agent"];
        var evaluators = ResolveEvaluators(evaluatorNames);

        var project = new AIProjectClient(new Uri(endpoint), Credentials.Default());
        var grader = new FoundryEvals(project, judgeModel, evaluators);
        var agent = project.AsAIAgent(model: agentModel, instructions: definition.Instructions, name: "asg-eval-support-explainer");

        Console.WriteLine();
        var failures = 0;
        for (var i = 0; i < cases.Count; i++)
        {
            var (testCase, query, context) = (cases[i], queries[i], contexts[i]);
            // Evaluating with the agent itself would send it the bare query and
            // attach `context` to the grading item only, so the agent would
            // answer blind and groundedness would score it against evidence it
            // never saw. Run it ourselves with the evidence, then grade that
            // response against the clean question.
            var response = await agent.RunAsync(new ChatMessage(ChatRole.User, GroundedPrompt(query, context)));
            var item = new EvalItem(query, response.Text, [new ChatMessage(ChatRole.User, query), .. response.Messages])
            {
                Context = context,
            };
            var caseId = testCase.GetProperty("id").ToString();
            var results = await grader.EvaluateAsync([item], $"asg-{caseId}");
            if (Report(caseId, [results]))
            {
                failures++;
            }
        }
        return failures;
    }

    private static async Task<int> RunAsync(string[] evaluatorNames, bool apply)
    {
        var endpoint = Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") is { Length: > 0 } project
            ? project
            : Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_ENDPOINT") ?? "";
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. Run .\\dotnet\\scripts\\populate-env.ps1 first.");
            return 2;
        }

        var agentModel = Environment.GetEnvironmentVariable("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER") ?? "";
        // Grading with the model under test is the cheap default, but a separate
        // judge deployment keeps the grader honest when one is configured.
        var judgeModel = Environment.GetEnvironmentVariable("FOUNDRY_MODEL_DEPLOYMENT_JUDGE") is { Length: > 0 } judge ? judge : agentModel;
        if (agentModel.Length == 0)
        {
            Console.Error.WriteLine("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER is not set.");
            return 2;
        }

        var cases = LoadCases();
        var queries = cases.Select(c => c.GetProperty("concern_text").ToString()).ToList();
        var contexts = new List<string>();
        foreach (var testCase in cases)
        {
            contexts.Add(await BuildContextAsync(testCase));
        }

        Console.WriteLine($"Evaluating {cases.Count} case(s)");
        Console.WriteLine($"  agent model : {agentModel}");
        Console.WriteLine($"  judge model : {judgeModel}");
        Console.WriteLine($"  evaluators  : {string.Join(", ", evaluatorNames)}");

        if (!apply)
        {
            Console.WriteLine("\nDry run. Nothing was sent to Azure. Re-run with --apply to grade.");
            for (var i = 0; i < cases.Count; i++)
            {
                Console.WriteLine($"  {cases[i].GetProperty("id")}: {PyText.Len(contexts[i])} chars of grounding context");
            }
            return 0;
        }

        int failures;
        try
        {
            failures = await GradeAllAsync(endpoint, agentModel, judgeModel, evaluatorNames, cases, queries, contexts);
        }
        catch (UnknownEvaluatorException exc)
        {
            Console.Error.WriteLine(exc.Message);
            return 1;
        }
        Console.WriteLine($"\n{cases.Count - failures}/{cases.Count} case(s) passed the quality gate.");
        return failures > 0 ? 1 : 0;
    }

    /// <summary>Flatten results -> per-item results -> scores into (name, score, passed).</summary>
    private static List<(string Name, double Score, bool? Passed)> CollectScores(IEnumerable<AgentEvaluationResults> runs) =>
        [.. runs.SelectMany(run => run.DetailedItems ?? [])
            .SelectMany(item => item.Scores ?? [])
            .Select(score => (score.Name is { Length: > 0 } name ? name : "?", score.Score, score.Passed))];

    /// <summary>Print one line per case. Returns true if this case regressed.</summary>
    /// <remarks>
    /// A run that produced no scores is a FAILURE, not a pass: it means the
    /// grader did not actually grade anything.
    /// </remarks>
    private static bool Report(string caseId, IReadOnlyList<AgentEvaluationResults> runs)
    {
        var statusErrors = runs
            .Where(r => (r.Status ?? "completed") != "completed")
            .Select(r => $"{r.Status ?? "?"}: {(r.Error is { Length: > 0 } error ? error : "no detail")}")
            .ToList();
        if (statusErrors.Count > 0)
        {
            Console.WriteLine($"  [fail] {caseId}: grader did not complete - {string.Join("; ", statusErrors)}");
            return true;
        }

        var scores = CollectScores(runs);
        if (scores.Count == 0)
        {
            Console.WriteLine($"  [fail] {caseId}: grader returned no scores - nothing was graded");
            return true;
        }

        // The grader's own verdict wins where it has one: a rubric can reject a
        // response that still scores above our local threshold.
        var below = scores.Where(s => s.Score < PassThreshold).Select(s => s.Name).ToList();
        var rejected = scores.Where(s => s.Passed == false).Select(s => s.Name).ToList();
        // A missing verdict is a failed verdict: defaulting to true would let an
        // SDK shape change silently turn a regression into a green run.
        var allPassed = runs.All(r => r.AllPassed);
        var regressed = below.Count > 0 || rejected.Count > 0 || !allPassed;

        var detail = string.Join(", ", scores
            .OrderBy(s => s.Name, StringComparer.Ordinal)
            .ThenBy(s => s.Score)
            .Select(s => $"{s.Name}={PyFloat.Fixed(s.Score, 2)}"));
        Console.WriteLine($"  [{(regressed ? "fail" : "ok  ")}] {caseId}  {detail}");
        if (rejected.Count > 0)
        {
            Console.WriteLine($"           grader rejected: {string.Join(", ", rejected.Distinct().Order(StringComparer.Ordinal))}");
        }

        if (runs.Select(r => r.ReportUrl).FirstOrDefault(url => url is not null) is { } reportUrl)
        {
            Console.WriteLine($"           report: {reportUrl}");
        }
        return regressed;
    }

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

    private sealed class UnknownEvaluatorException(string message) : Exception(message);
}
