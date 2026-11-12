using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using Microsoft.AspNetCore.Http;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Tests proving dealer group A requests can never see dealer group B evidence.</summary>
public sealed class DealerGroupIsolationTests
{
    // test_agents.py's _analyst_ctx and _bundle, which the Python module imports.
    // AgentsTests keeps its copies private, so they are repeated here.
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

    // Pydantic validates SupportPlanRequest on construction. This track
    // validates a request body as the endpoint reads it, returning null and
    // naming the failing fields where Pydantic raises.
    private static async Task<SupportPlanRequest?> ParseSupportPlanRequestAsync(JsonObject body, List<string> errors)
    {
        var context = new DefaultHttpContext();
        context.Request.ContentType = "application/json";
        context.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes(body.ToJsonString()));
        return RequestModels.ParseSupportPlanRequest(await JsonBody.ReadAsync(context), errors);
    }

    [Fact]
    public async Task Fixture_retriever_never_returns_other_dealer_groups()
    {
        var retriever = new FixtureEvidenceRetriever();
        foreach (var group in FixtureEvidenceRetriever.ListAvailableDealerGroups())
        {
            var bundle = await retriever.RetrieveAsync(
                new EvidenceRequest(DealerGroupId: group, Category: "lead-response", DetectedNeedHint: ""),
                TestContext.Current.CancellationToken);
            foreach (var c in bundle.Citations)
            {
                Assert.True(
                    c.DealerGroupId == group,
                    $"retriever leaked a citation from {c.DealerGroupId} into request for {group}");
            }
        }
    }

    [Fact]
    public async Task Fixture_retriever_returns_empty_for_unknown_category()
    {
        var retriever = new FixtureEvidenceRetriever();
        var bundle = await retriever.RetrieveAsync(
            new EvidenceRequest(
                DealerGroupId: "GROUP-DEMO",
                Category: "__does_not_exist__",
                DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.Empty(bundle.Citations);
    }

    [Fact]
    public async Task Two_dealer_groups_receive_different_citations()
    {
        var retriever = new FixtureEvidenceRetriever();
        var a = await retriever.RetrieveAsync(
            new EvidenceRequest(DealerGroupId: "GROUP-A", Category: "lead-response", DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        var b = await retriever.RetrieveAsync(
            new EvidenceRequest(DealerGroupId: "GROUP-B", Category: "lead-response", DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        var aIds = a.Citations.Select(c => c.CitationId).ToHashSet();
        var bIds = b.Citations.Select(c => c.CitationId).ToHashSet();
        Assert.False(aIds.Overlaps(bIds));
    }

    /// <summary>Draft carries a GROUP-B citation for a GROUP-A request - must fail.</summary>
    [Fact]
    public async Task Validator_rejects_cross_dealer_group_citation()
    {
        var client = new FakeChatClientFactory();
        client.RegisterResponse("data-analyst-agent", Conftest.CannedDataAnalystOutput());
        client.RegisterResponse(
            "support-recommendation-agent",
            Conftest.CannedRecommendationDraft(
                goalIds: ["GOAL-lead-response-1"],
                strategyIds: ["ST-lead-response-1"]));
        client.RegisterResponse("validator-agent", Conftest.CannedValidatorCritique());
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);

        var retriever = new FixtureEvidenceRetriever();
        var distBBundle = await retriever.RetrieveAsync(
            new EvidenceRequest(DealerGroupId: "GROUP-B", Category: "lead-response", DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        var ctx = new SupportRecommenderContext(
            DealerGroupId: "GROUP-A", // Request dealer group
            Category: "lead-response",
            ConcernText: "synthetic",
            AllowedResources: [],
            AllowedGoalIds: ["GOAL-lead-response-1"],
            AllowedStrategyIds: ["ST-lead-response-1"],
            Evidence: distBBundle); // But bundle is from GROUP-B (illegal)
        var analysis = await new DataAnalystAgent(runtime).AnalyzeAsync(AnalystCtx(), TestContext.Current.CancellationToken);
        var draft = await new SupportRecommendationAgent(runtime).RecommendAsync(analysis, ctx, cancellationToken: TestContext.Current.CancellationToken);
        // The wrapper resolves cited_ids against the supplied bundle, so a model
        // can no longer smuggle in another dealer group's citation. Attach one
        // directly to prove the validator still catches it defensively.
        draft = draft with { Citations = [.. distBBundle.Citations] };
        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: "GROUP-A",
                    AllowedResourceIds: [],
                    AllowedGoalIds: ["GOAL-lead-response-1"],
                    AllowedStrategyIds: ["ST-lead-response-1"],
                    AllowedCitationIds: [.. distBBundle.Citations.Select(c => c.CitationId)],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: false,
            TestContext.Current.CancellationToken);
        Assert.False(report.Passed);
        Assert.Contains("CROSS_DEALER_GROUP_CITATION", report.IssueCodes);
        Assert.Contains("citations", report.FailedFields);
    }

    /// <summary>Draft carries a citation whose citation_id is not in allowed set.</summary>
    [Fact]
    public async Task Validator_rejects_unknown_source_ref()
    {
        var client = new FakeChatClientFactory();
        client.RegisterResponse("validator-agent", Conftest.CannedValidatorCritique());
        var (runtime, _) = FakeChatClientFactory.MakeFakeRuntime(client);
        // Build a synthetic draft directly to bypass wrapper attaching citations.
        var fakeC = new Citation(
            CitationId: "FAKE-INVENTED",
            DealerGroupId: Conftest.DefaultDealerGroup,
            SourceType: CitationSourceType.SyntheticFixture,
            SourceTitle: "Invented",
            SectionOrPage: "",
            EvidenceSummary: "Not in allowed set.",
            SourceRef: "fixture://demo/invented",
            RetrievedAt: DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
            Confidence: 0.5);
        var draft = new SupportRecommendationDraft(
            // Pydantic's default for the field the Python test leaves out.
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
            Citations: [fakeC]);
        var analysis = DataAnalystOutput.Create(
            Contracts.ContractVersion,
            Conftest.DefaultDealerGroup,
            new AnalysisSummary(
                DetectedNeed: "n", EvidenceBullets: [], MissingDataFlags: [], AnalysisConfidence: 0.5));
        var realBundle = await BundleAsync();
        var report = await new ValidatorAgent(runtime).ValidateAsync(
            new ValidatorInput(
                Analysis: analysis,
                Draft: draft,
                Context: new ValidatorContext(
                    DealerGroupId: Conftest.DefaultDealerGroup,
                    AllowedResourceIds: [],
                    AllowedGoalIds: [],
                    AllowedStrategyIds: [],
                    AllowedCitationIds: [.. realBundle.Citations.Select(c => c.CitationId)],
                    RequiredContractVersion: "1.0.0")),
            useLlmCritique: false,
            TestContext.Current.CancellationToken);
        Assert.False(report.Passed);
        Assert.Contains("UNKNOWN_CITATION_ID", report.IssueCodes);
    }

    /// <summary>The API-level request model refuses missing dealer_group_id.</summary>
    [Fact]
    public async Task Recommendation_request_requires_dealer_group_id()
    {
        var errors = new List<string>();
        var request = await ParseSupportPlanRequestAsync(
            new JsonObject
            {
                ["dealership_id"] = "DLR-0001",
                ["category"] = "lead-response",
                ["concern_text"] = "Median first response to online enquiries slipped past one hour.",
            },
            errors);
        // pytest.raises(ValidationError): rejected, with at least one failing field.
        Assert.Null(request);
        Assert.NotEmpty(errors);
    }
}
