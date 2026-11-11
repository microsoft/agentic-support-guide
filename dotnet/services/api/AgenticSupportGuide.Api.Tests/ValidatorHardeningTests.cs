using System.Text;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

public sealed class ValidatorHardeningTests
{
    // Python's inspect.getsource(checks): this track's source file.
    private static readonly string ChecksSource = Path.Combine(
        Conformance.Goldens.RepoRoot, "dotnet", "services", "api", "AgenticSupportGuide.Api", "Agents", "Validator", "Checks.cs");

    // No Roslyn here, so Python's AST walk becomes a match on `.Flag(` and its first argument.
    private static readonly Regex FlagCall = new(
        """\.Flag\(\s*(?:(?<literal>"(?:[^"\\\r\n]|\\.)*"|@"(?:[^"]|"")*")(?=\s*[,)])|(?<other>[^,)]*))""",
        RegexOptions.CultureInvariant);

    // test_agents.py's helpers, which are private to AgentsTests here.
    private static DataAnalystContext AnalystCtx() => new(
        DealerGroupId: Conftest.DefaultDealerGroup,
        DealershipLabel: "Dealership 0001",
        Segment: "SEG-VOLUME",
        RegionId: "REG-001",
        ProcessScore: 45.0,
        AppointmentAttendanceRate: 0.9,
        FollowupIndex: 70.0,
        EngagementIndex: 65.0,
        AreaSeries: Conftest.SampleAreaSeries(),
        OperationsSeries: Conftest.SampleOperationsSeries(),
        Category: "lead-response",
        ConcernText: "First response to online enquiries is slower than the standard.");

    private static async Task<EvidenceBundle> BundleAsync()
    {
        var retriever = new FixtureEvidenceRetriever();
        return await retriever.RetrieveAsync(
            new EvidenceRequest(
                DealerGroupId: Conftest.DefaultDealerGroup,
                Category: "lead-response",
                DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
    }

    private static async Task<SupportRecommenderContext> RecCtxAsync() => new(
        DealerGroupId: Conftest.DefaultDealerGroup,
        Category: "lead-response",
        ConcernText: "synthetic",
        AllowedResources: [],
        AllowedGoalIds: ["GOAL-lead-response-1"],
        AllowedStrategyIds: ["ST-lead-response-1"],
        Evidence: await BundleAsync());

    private static MafAgentRuntime RuntimeWithAdversarialCritique(Dictionary<string, object?> critique)
    {
        var client = new FakeChatClientFactory();
        client.RegisterResponse(
            "data-analyst-agent",
            Conftest.CannedDataAnalystOutput());
        client.RegisterResponse(
            "support-recommendation-agent",
            Conftest.CannedRecommendationDraft(
                goalIds: ["GOAL-lead-response-1"],
                strategyIds: ["ST-lead-response-1"]));
        client.RegisterResponse(
            "validator-agent",
            critique);
        return FakeChatClientFactory.MakeFakeRuntime(client).Runtime;
    }

    [Fact]
    public async Task Validator_drops_non_conforming_llm_warnings()
    {
        var runtime = RuntimeWithAdversarialCritique(
            new Dictionary<string, object?>
            {
                ["warning_codes"] = new List<string>
                {
                    "leaked user secret abcdef",
                    "here is the concern: password=hunter2",
                    "OK",
                    "REAL_WARNING_CODE",
                    "lower_case_should_drop",
                    "  TRIMMED_CODE  ",
                },
                ["repair_guidance"] = "",
            });
        var analysis = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var draft = await new SupportRecommendationAgent(runtime).RecommendAsync(analysis, await RecCtxAsync(), cancellationToken: TestContext.Current.CancellationToken);
        var bundle = await BundleAsync();
        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: Conftest.DefaultDealerGroup,
                    AllowedResourceIds: [],
                    AllowedGoalIds: ["GOAL-lead-response-1"],
                    AllowedStrategyIds: ["ST-lead-response-1"],
                    AllowedCitationIds: [.. bundle.Citations.Select(c => c.CitationId)],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: true,
            TestContext.Current.CancellationToken);
        Assert.Equal(new HashSet<string> { "REAL_WARNING_CODE", "TRIMMED_CODE" }, report.WarningCodes.ToHashSet());
        foreach (var w in report.WarningCodes)
        {
            Assert.DoesNotContain("password", PyText.Lower(w), StringComparison.Ordinal);
            Assert.DoesNotContain("concern", PyText.Lower(w), StringComparison.Ordinal);
        }
    }

    /// <summary>Catches a new validator rule that forgot its repair template.</summary>
    /// <remarks>
    /// The codes are read out of Checks.cs rather than listed here, so adding a
    /// rule cannot pass by also updating a hand-maintained list in this test.
    /// </remarks>
    [Fact]
    public void Every_issue_code_a_check_can_emit_has_repair_guidance()
    {
        var source = CodeWithoutCommentLines(ChecksSource);
        var calls = FlagCall.Matches(source).ToList();
        Assert.True(calls.Count > 0, "found no findings.Flag(...) calls; the source scan is broken");

        // A code built at runtime cannot be checked against the templates, so the
        // scan refuses to pass rather than reporting coverage it did not verify.
        var dynamicCalls = calls.Where(call => !call.Groups["literal"].Success).ToList();
        Assert.True(
            dynamicCalls.Count == 0,
            "findings.Flag() called with a non-literal issue code at line(s) "
            + $"[{string.Join(", ", dynamicCalls.Select(call => LineOf(source, call.Index)).Order())}]; this test cannot verify those");

        var emitted = calls
            .Where(call => call.Groups["literal"].Success)
            .Select(call => LiteralValue(call.Groups["literal"].Value))
            .ToHashSet();
        Assert.True(
            emitted.IsSubsetOf(Repair.RepairableIssueCodes),
            $"issue codes with no repair template: {PyText.ReprList(emitted.Except(Repair.RepairableIssueCodes).Order(StringComparer.Ordinal))}");
    }

    // Comment lines blanked, not removed, so line numbers still hold.
    private static string CodeWithoutCommentLines(string path) =>
        string.Join("\n", File.ReadAllLines(path, Encoding.UTF8).Select(line => line.TrimStart().StartsWith("//", StringComparison.Ordinal) ? "" : line));

    private static int LineOf(string text, int index) => text.AsSpan(0, index).Count('\n') + 1;

    // Issue codes carry no escapes.
    private static string LiteralValue(string literal) =>
        literal[0] == '@' ? literal[2..^1].Replace("\"\"", "\"", StringComparison.Ordinal) : literal[1..^1];
}
