using AgenticSupportGuide.Api.FoundryAgents;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// The Python tests' shared fixtures (tests/conftest.py), as plain helpers.
/// </summary>
/// <remarks>
/// Every test starts from the same environment the Python autouse fixture
/// sets: no app settings, and the three role deployments present.
/// <see cref="TestApp.Start"/> applies that slate.
/// </remarks>
public static class Conftest
{
    private static readonly string[] SamplePeriods = ["2026-07", "2026-08", "2026-09"];

    public const string DefaultDealerGroup = "GROUP-DEMO";

    /// <summary>A small but real series, so tests exercise the shape the analyst gets.</summary>
    public static AreaSeries SampleAreaSeries() => new(
        Periods: SamplePeriods,
        ScoresByArea: new Dictionary<string, IReadOnlyList<int?>>
        {
            ["lead-response"] = [52, 48, 44],
            ["test-drive-conversion"] = [61, 62, 60],
        },
        LatestBandByArea: new Dictionary<string, string>
        {
            ["lead-response"] = "Developing",
            ["test-drive-conversion"] = "On track",
        },
        RecordCount: 6);

    public static OperationsSeries SampleOperationsSeries() => new(
        Periods: SamplePeriods,
        AppointmentAttendanceRate: [0.91, 0.88, 0.84],
        Escalations: [1, 2, 3],
        FollowupCompletion: [72.0, 68.5, 64.0],
        RecordCount: 3);

    // ---------------------------------------------------------------------
    // Canonical canned agent outputs used across tests
    // ---------------------------------------------------------------------

    public static Dictionary<string, object?> CannedDataAnalystOutput() => new()
    {
        ["contract_version"] = "1.0.0",
        ["analysis"] = new Dictionary<string, object?>
        {
            ["detected_need"] = "Slow enquiry response",
            ["evidence_bullets"] = new List<string>
            {
                "Process score below target across two periods.",
                "Appointment attendance within expected range.",
            },
            ["missing_data_flags"] = new List<string>(),
            ["analysis_confidence"] = 0.8,
        },
    };

    public static Dictionary<string, object?> CannedRecommendationDraft(
        List<string>? resourceIds = null,
        List<string>? goalIds = null,
        List<string>? strategyIds = null,
        string tier = "Focused",
        List<string>? caveats = null,
        List<string>? citedIds = null)
    {
        return new()
        {
            ["contract_version"] = "1.0.0",
            ["detected_need"] = "Enquiry response slower than the group standard",
            ["support_tier"] = tier,
            ["recommended_frequency"] = "weekly review, 20-25 min",
            ["grouping_guidance"] = "single dealership with group oversight",
            ["resource_ids"] = resourceIds ?? [],
            ["rationale"] = "Synthetic dealership indicators support focused lead-response work.",
            ["goal_suggestions"] = goalIds ?? [],
            ["strategy_suggestions"] = strategyIds ?? [],
            ["manager_next_steps"] = new List<string> { "Confirm the baseline with a short synthetic check." },
            ["progress_monitoring"] = new List<string> { "Weekly check on the agreed measure." },
            ["review_window_days"] = 28,
            ["decision_rule"] = "IF process_score < 60 THEN targeted.",
            ["caveats"] = caveats ??
            [
                "Illustrative synthetic output only; not a real benchmark.",
                "Human review is required before any decision or communication.",
            ],
            // Citations are no longer auto-attached when the model cites nothing,
            // so the canned draft must cite explicitly like a real one would.
            ["cited_ids"] = citedIds ?? ["GROUP-DEMO-lead-01", "GROUP-DEMO-lead-02"],
        };
    }

    public static Dictionary<string, object?> CannedValidatorCritique() => new()
    {
        ["warning_codes"] = new List<string>(),
        ["repair_guidance"] = "",
    };

    // ---------------------------------------------------------------------
    // Fixtures
    // ---------------------------------------------------------------------

    public static FakeChatClientFactory CannedFactory(List<string>? resourceIds = null, List<string>? goalIds = null, List<string>? strategyIds = null)
    {
        var factory = new FakeChatClientFactory();
        factory.RegisterResponse("data-analyst-agent", CannedDataAnalystOutput());
        factory.RegisterResponse(
            "support-recommendation-agent",
            CannedRecommendationDraft(
                resourceIds: resourceIds,
                goalIds: goalIds is { Count: > 0 } ? goalIds : ["GOAL-lead-response-1"],
                strategyIds: strategyIds is { Count: > 0 } ? strategyIds : ["ST-lead-response-1"]));
        factory.RegisterResponse("validator-agent", CannedValidatorCritique());
        return factory;
    }

    public static MafAgentRuntime FakeRuntime(FakeChatClientFactory? factory = null) =>
        FakeChatClientFactory.MakeFakeRuntime(factory ?? CannedFactory()).Runtime;

    /// <summary>
    /// The app as the web tier reaches it: a fake runtime, a configured
    /// project endpoint, and the shared key on every request.
    /// </summary>
    /// <remarks>
    /// Tests send a real key rather than leaving it unset, so the comparison
    /// path runs. Clearing the key in tests would make every endpoint test
    /// blind to whether the check is wired up at all.
    /// </remarks>
    public static TestApp MakeClient(
        MafAgentRuntime? runtime = null,
        bool demoResetEnabled = false,
        string? projectEndpoint = FakeChatClientFactory.DefaultEndpoint,
        IReadOnlyDictionary<string, string>? environment = null)
    {
        var settings = new Dictionary<string, string>
        {
            ["AZURE_AI_FOUNDRY_AUTH_MODE"] = "entra",
            ["API_SHARED_KEY"] = TestApp.TestApiKey,
        };
        if (projectEndpoint is not null)
        {
            settings["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"] = projectEndpoint;
        }
        if (demoResetEnabled)
        {
            settings["DEMO_RESET_ENABLED"] = "true";
        }
        foreach (var (name, value) in environment ?? new Dictionary<string, string>())
        {
            settings[name] = value;
        }
        var app = TestApp.Start(settings, runtime: () => runtime ?? FakeRuntime());
        app.Client.DefaultRequestHeaders.Add("x-api-key", TestApp.TestApiKey);
        return app;
    }

    public static TestApp MakeDefaultClient(bool demoResetEnabled = false) => MakeClient(demoResetEnabled: demoResetEnabled);
}
