using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

public sealed class ValidatorCitationChecksTests
{
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

    private static void Seed(FakeChatClientFactory client)
    {
        client.RegisterResponse("data-analyst-agent", Conftest.CannedDataAnalystOutput());
        client.RegisterResponse(
            "support-recommendation-agent",
            Conftest.CannedRecommendationDraft(
                goalIds: ["GOAL-lead-response-1"], strategyIds: ["ST-lead-response-1"]));
        client.RegisterResponse("validator-agent", Conftest.CannedValidatorCritique());
    }

    private static async Task<EvidenceBundle> BundleFromCtxAsync() => (await RecCtxAsync()).Evidence;

    /// <summary>Empty citations list on the draft must trigger MISSING_CITATIONS.</summary>
    [Fact]
    public async Task Validator_fails_on_missing_citations()
    {
        var client = new FakeChatClientFactory();
        Seed(client);
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);

        var emptyBundle = new EvidenceBundle(DealerGroupId: Conftest.DefaultDealerGroup, Citations: []);
        var ctx = new SupportRecommenderContext(
            DealerGroupId: Conftest.DefaultDealerGroup,
            Category: "lead-response",
            ConcernText: "synthetic",
            AllowedResources: [],
            AllowedGoalIds: ["GOAL-lead-response-1"],
            AllowedStrategyIds: ["ST-lead-response-1"],
            Evidence: emptyBundle);
        var analysis = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var draft = await new SupportRecommendationAgent(runtime).RecommendAsync(analysis, ctx, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Empty(draft.Citations);

        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: Conftest.DefaultDealerGroup,
                    AllowedResourceIds: [],
                    AllowedGoalIds: ["GOAL-lead-response-1"],
                    AllowedStrategyIds: ["ST-lead-response-1"],
                    AllowedCitationIds: [],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: false,
            TestContext.Current.CancellationToken);
        Assert.False(report.Passed);
        Assert.Contains("MISSING_CITATIONS", report.IssueCodes);
        Assert.Contains("citations", report.FailedFields);
        Assert.StartsWith("Validator failed on:", report.SafeSummary, StringComparison.Ordinal);
    }

    /// <summary>Draft committing to a trade-in value must trigger FORBIDDEN_DETERMINATION.</summary>
    [Fact]
    public async Task Validator_flags_forbidden_determination_language()
    {
        var citation = new Citation(
            CitationId: "GROUP-DEMO-el-01",
            DealerGroupId: Conftest.DefaultDealerGroup,
            SourceType: CitationSourceType.SyntheticFixture,
            SourceTitle: "Fixture",
            SectionOrPage: "",
            EvidenceSummary: "synthetic",
            SourceRef: "fixture://demo/el-01",
            RetrievedAt: "2026-01-05T09:00:00Z",
            Confidence: 0.7);
        var draft = new SupportRecommendationDraft(
            ContractVersion: Contracts.ContractVersion,
            DealerGroupId: Conftest.DefaultDealerGroup,
            DetectedNeed: "synthetic",
            SupportTier: "Focused support",
            RecommendedFrequency: "3x weekly",
            GroupingGuidance: "small group",
            ResourceIds: [],
            Rationale: "The synthetic dealership should tell the customer their trade-in is worth $8,500.",
            GoalSuggestions: [],
            StrategySuggestions: [],
            ManagerNextSteps: ["Confirm baseline."],
            ProgressMonitoring: ["Weekly probe."],
            ReviewWindowDays: 28,
            DecisionRule: "IF baseline low THEN targeted.",
            Caveats: ["Human review is required before any decision."],
            Citations: [citation]);
        var analysis = DataAnalystOutput.Create(
            contractVersion: Contracts.ContractVersion,
            dealerGroupId: Conftest.DefaultDealerGroup,
            analysis: new AnalysisSummary(
                DetectedNeed: "n", EvidenceBullets: [], MissingDataFlags: [], AnalysisConfidence: 0.5));

        var client = new FakeChatClientFactory();
        Seed(client);
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: Conftest.DefaultDealerGroup,
                    AllowedResourceIds: [],
                    AllowedGoalIds: [],
                    AllowedStrategyIds: [],
                    AllowedCitationIds: ["GROUP-DEMO-el-01"],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: false,
            TestContext.Current.CancellationToken);
        Assert.False(report.Passed);
        Assert.Contains("FORBIDDEN_DETERMINATION", report.IssueCodes);
    }

    [Fact]
    public async Task Validator_safe_summary_never_contains_raw_critique()
    {
        // Register a validator LLM critique with adversarial free text.
        var client = new FakeChatClientFactory();
        client.RegisterResponse(
            "validator-agent",
            new Dictionary<string, object?>
            {
                ["warning_codes"] = new List<string> { "real free-text leak here" },
                ["repair_guidance"] = "the user's raw concern text is ...",
            });
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);

        var citation = new Citation(
            CitationId: "GROUP-DEMO-el-01",
            DealerGroupId: Conftest.DefaultDealerGroup,
            SourceType: CitationSourceType.SyntheticFixture,
            SourceTitle: "Fixture",
            SectionOrPage: "",
            EvidenceSummary: "synthetic",
            SourceRef: "fixture://demo/el-01",
            RetrievedAt: "2026-01-05T09:00:00Z",
            Confidence: 0.7);
        var draft = new SupportRecommendationDraft(
            ContractVersion: Contracts.ContractVersion,
            DealerGroupId: Conftest.DefaultDealerGroup,
            DetectedNeed: "synthetic",
            SupportTier: "Focused support",
            RecommendedFrequency: "3x weekly",
            GroupingGuidance: "small group",
            ResourceIds: [],
            Rationale: "synthetic",
            GoalSuggestions: [],
            StrategySuggestions: [],
            ManagerNextSteps: ["Confirm baseline."],
            ProgressMonitoring: ["Weekly probe."],
            ReviewWindowDays: 28,
            DecisionRule: "IF baseline low THEN targeted.",
            Caveats: ["Human review is required before any decision."],
            Citations: [citation]);
        var analysis = DataAnalystOutput.Create(
            contractVersion: Contracts.ContractVersion,
            dealerGroupId: Conftest.DefaultDealerGroup,
            analysis: new AnalysisSummary(
                DetectedNeed: "n", EvidenceBullets: [], MissingDataFlags: [], AnalysisConfidence: 0.5));
        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: Conftest.DefaultDealerGroup,
                    AllowedResourceIds: [],
                    AllowedGoalIds: [],
                    AllowedStrategyIds: [],
                    AllowedCitationIds: ["GROUP-DEMO-el-01"],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: true,
            TestContext.Current.CancellationToken);
        // `SafeSummary` and `WarningCodes` must not carry the raw free-text.
        Assert.DoesNotContain("raw concern", PyText.Lower(report.SafeSummary), StringComparison.Ordinal);
        // The leaky code was lowercase with spaces, so `EnforceCode` drops it.
        // Assert that rather than looping over what is now an empty list.
        Assert.Empty(report.WarningCodes);
        Assert.DoesNotContain("the user's raw concern text", PyText.Lower(report.RepairGuidance), StringComparison.Ordinal);
        _ = (Func<Task<EvidenceBundle>>)BundleFromCtxAsync; // silence unused
    }
}
