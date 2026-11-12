using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

public sealed class AgentsTests
{
    private static (FakeChatClientFactory Client, Dictionary<string, object?> Extra) SeedClient(
        List<string>? resourceIds = null,
        List<string>? goalIds = null,
        List<string>? strategyIds = null,
        string tier = "Focused",
        List<string>? caveats = null,
        List<string>? citedIds = null)
    {
        var client = new FakeChatClientFactory();
        client.RegisterResponse(
            "data-analyst-agent",
            Conftest.CannedDataAnalystOutput());
        client.RegisterResponse(
            "support-recommendation-agent",
            Conftest.CannedRecommendationDraft(
                resourceIds: resourceIds,
                goalIds: goalIds is { Count: > 0 } ? goalIds : ["GOAL-lead-response-1"],
                strategyIds: strategyIds is { Count: > 0 } ? strategyIds : ["ST-lead-response-1"],
                tier: tier,
                caveats: caveats,
                citedIds: citedIds));
        client.RegisterResponse(
            "validator-agent",
            Conftest.CannedValidatorCritique());
        return (client, new Dictionary<string, object?>());
    }

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

    [Fact]
    public async Task Data_analyst_agent_returns_typed_output()
    {
        var (client, _) = SeedClient();
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        var result = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        Assert.Equal("1.0.0", result.ContractVersion);
        Assert.Equal(Conftest.DefaultDealerGroup, result.DealerGroupId);
        Assert.False(string.IsNullOrEmpty(result.Analysis.DetectedNeed));
    }

    /// <summary>
    /// The agent is asked for cross-area and temporal analysis, so it has to
    /// receive both series. It previously got only a record count, and every test
    /// still passed because none of them inspected the outbound prompt.
    /// </summary>
    [Fact]
    public async Task Analyst_prompt_carries_the_score_and_operations_series()
    {
        var (client, _) = SeedClient();
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);

        var prompt = client.Calls().First(c => c.Role == "data-analyst-agent").UserMessage;
        var match = Regex.Match(prompt, @"kind=synthetic_facts\n(.*?)\n<<<END", RegexOptions.Singleline);
        Assert.True(match.Success, "the analyst prompt carries no synthetic_facts block");
        var facts = JsonNode.Parse(match.Groups[1].Value)!;

        var series = AnalystCtx().AreaSeries;
        Assert.Equal(series.Periods, facts["score_periods"]!.AsArray().Select(n => n!.GetValue<string>()));
        Assert.Equal(
            series.ScoresByArea["lead-response"],
            facts["score_by_process_area"]!["lead-response"]!.AsArray().Select(n => n is null ? (int?)null : n.GetValue<int>()));
        Assert.Equal("Developing", facts["latest_band_by_process_area"]!["lead-response"]!.GetValue<string>());

        var ops = AnalystCtx().OperationsSeries;
        Assert.Equal(ops.AppointmentAttendanceRate, facts["appointment_attendance_rate_by_period"]!.AsArray().Select(n => n!.GetValue<double>()));
        Assert.Equal(ops.Escalations, facts["escalations_by_period"]!.AsArray().Select(n => n!.GetValue<int>()));
        Assert.Equal(ops.FollowupCompletion, facts["followup_completion_by_period"]!.AsArray().Select(n => n!.GetValue<double>()));
    }

    /// <summary>The facts block is sanitised on the way out; it must still parse.</summary>
    [Fact]
    public async Task Analyst_prompt_reaches_the_model_as_valid_json()
    {
        var (client, _) = SeedClient();
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var prompt = client.Calls().First(c => c.Role == "data-analyst-agent").UserMessage;
        var match = Regex.Match(prompt, @"kind=synthetic_facts\n(.*?)\n<<<END", RegexOptions.Singleline);
        Assert.True(match.Success, "the analyst prompt carries no synthetic_facts block");
        Assert.IsType<JsonObject>(JsonNode.Parse(match.Groups[1].Value));
    }

    [Fact]
    public async Task Support_recommender_attaches_dealer_group_citations()
    {
        var (client, _) = SeedClient();
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        var analysis = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var draft = await new SupportRecommendationAgent(runtime).RecommendAsync(analysis, await RecCtxAsync(), cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(Conftest.DefaultDealerGroup, draft.DealerGroupId);
        Assert.True(draft.Citations.Count >= 1);
        foreach (var c in draft.Citations)
        {
            Assert.Equal(Conftest.DefaultDealerGroup, c.DealerGroupId);
        }
    }

    [Fact]
    public async Task Support_recommender_respects_cited_ids_selection()
    {
        var bundle = await BundleAsync();
        var firstId = bundle.Citations[0].CitationId;
        var (client, _) = SeedClient(citedIds: [firstId]);
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        var analysis = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var draft = await new SupportRecommendationAgent(runtime).RecommendAsync(analysis, await RecCtxAsync(), cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal([firstId], draft.Citations.Select(c => c.CitationId));
    }

    [Fact]
    public async Task Validator_pass_with_valid_citations()
    {
        var (client, _) = SeedClient();
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
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
        Assert.True(report.Passed, PyText.ReprList(report.IssueCodes));
        Assert.Equal(Conftest.DefaultDealerGroup, report.DealerGroupId);
        Assert.False(string.IsNullOrEmpty(report.SafeSummary));
        Assert.Empty(report.FailedFields);
    }

    [Fact]
    public async Task Validator_flags_unknown_resource()
    {
        var (client, _) = SeedClient(resourceIds: ["RES-000-INVENTED"]);
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        var analysis = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var ctx = new SupportRecommenderContext(
            DealerGroupId: Conftest.DefaultDealerGroup,
            Category: "lead-response",
            ConcernText: "synthetic",
            AllowedResources: [new ResourceRef(Id: "RES-001", Label: "Kit", Kind: "guide")],
            AllowedGoalIds: ["GOAL-lead-response-1"],
            AllowedStrategyIds: ["ST-lead-response-1"],
            Evidence: await BundleAsync());
        var draft = await new SupportRecommendationAgent(runtime).RecommendAsync(analysis, ctx, cancellationToken: TestContext.Current.CancellationToken);
        var bundle = await BundleAsync();
        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: Conftest.DefaultDealerGroup,
                    AllowedResourceIds: ["RES-001"],
                    AllowedGoalIds: ["GOAL-lead-response-1"],
                    AllowedStrategyIds: ["ST-lead-response-1"],
                    AllowedCitationIds: [.. bundle.Citations.Select(c => c.CitationId)],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: false,
            TestContext.Current.CancellationToken);
        Assert.False(report.Passed);
        Assert.Contains("UNKNOWN_RESOURCE_ID", report.IssueCodes);
        Assert.Contains("resource_ids", report.FailedFields);
    }

    [Fact]
    public async Task Validator_flags_missing_caveats()
    {
        var (client, _) = SeedClient(caveats: []);
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
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
            useLlmCritique: false,
            TestContext.Current.CancellationToken);
        Assert.False(report.Passed);
        Assert.Contains("MISSING_CAVEATS", report.IssueCodes);
    }
}
