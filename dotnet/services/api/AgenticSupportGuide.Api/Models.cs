namespace AgenticSupportGuide.Api;

// The HTTP boundary. Property names serialize as snake_case (see PyJson),
// in the order declared here, which is the order the web app and the
// conformance goldens expect.

public sealed record HealthResponse(
    string Status,
    string Service,
    string Version,
    string Banner,
    bool ProviderConfigured,
    // How the API authenticates OUTBOUND to Foundry. Deliberately not named
    // `auth_mode`: this endpoint is anonymous, and a bare "entra" here reads as
    // "the API requires a sign-in", which it does not. Inbound protection is
    // `api_auth_mode` on /health/details.
    string FoundryAuthMode,
    // Proves which build is serving. A deploy can succeed and still leave the
    // previous code running, which no other field here would reveal.
    string BuildId);

public sealed record HealthCheckItem(string Name, string Label, bool Ok, string Detail);

public sealed record HealthDetailsResponse(
    string Status,
    string Service,
    string Version,
    string ActiveProvider,
    bool FoundryProjectConfigured,
    bool AgentDefinitionsValid,
    bool ModelDeploymentsConfigured,
    bool ServiceSideRemoteWorkflowActive,
    bool EvidenceFixtureAvailable,
    // Which retriever is actually serving evidence. Without this, a Module 6
    // misconfiguration looks identical to a working one from the outside.
    string EvidenceSource,
    string EvidenceKnowledgeBase,
    // False for a remote knowledge base: readiness is a configuration check and
    // cannot prove a remote source holds anything without a network call.
    bool EvidenceVerified,
    // `shared_key`, `unprotected` or `misconfigured`. Surfaced so an
    // unauthenticated deployment is visible from outside rather than only in
    // app settings.
    string ApiAuthMode,
    bool DealerGroupIsolationEnabled,
    bool CustomerDemoReady,
    IReadOnlyList<HealthCheckItem> Checks,
    IReadOnlyList<string> Warnings,
    string Guidance);

public sealed record DemoResetResponse(string Status, int PlansReset, int AuditReset);

public sealed record AgentTraceStep(
    string Agent,
    string Status,
    string Provider,
    string Model,
    int LatencyMs,
    int? TokenEstimate,
    IReadOnlyList<string> IssueCodes,
    IReadOnlyList<string> WarningCodes,
    int CitationCount);

public sealed record KpiCard(string Id, string Label, double Value, string Unit, double Delta, string Trend);

public sealed record TrendPoint(string Period, double Value);

public sealed record AreaSlice(string ProcessArea, double Value);

public sealed record DashboardSummary(
    IReadOnlyList<KpiCard> KpiCards,
    IReadOnlyList<TrendPoint> ProcessScoreTrend,
    IReadOnlyList<AreaSlice> AreaDistribution,
    IReadOnlyList<TrendPoint> EngagementTrend,
    IReadOnlyList<string> Notes);

public sealed record DealershipSummary(
    string DealershipId,
    string DisplayLabel,
    string RegionId,
    string Segment,
    double ProcessScore,
    double AppointmentAttendanceRate,
    double FollowupIndex,
    double EngagementIndex,
    bool Flagged);

public sealed record DealershipsResponse(IReadOnlyList<DealershipSummary> Dealerships, int Total);

public sealed record BandBucket(string Label, int Count, double Percent);

public sealed record AreaTrend(string ProcessArea, IReadOnlyList<TrendPoint> Points);

public sealed record ScoresSummary(
    IReadOnlyDictionary<string, string?> FiltersApplied,
    int TotalRecords,
    IReadOnlyList<BandBucket> BandDistribution,
    IReadOnlyList<AreaTrend> AreaTrends,
    IReadOnlyList<string> RecommendationBullets,
    string PerformanceSummary,
    string GeneratedBy,
    IReadOnlyList<IReadOnlyDictionary<string, object>> TableRows);

public sealed record OperationsSummary(
    IReadOnlyList<TrendPoint> AttendanceTrend,
    IReadOnlyList<TrendPoint> EscalationTrend,
    IReadOnlyList<TrendPoint> EngagementTrend,
    IReadOnlyList<string> Highlights,
    int TotalRecords);

public sealed record Option(string Id, string Label);

public sealed record CategoryOption(string Id, string Label, string Description);

public sealed record GoalOption(string Id, string Label, string CategoryId, string Description);

public sealed record StrategyOption(string Id, string Label, string CategoryId, string Description);

public sealed record SupportOptions(
    IReadOnlyList<Option> Dealerships,
    IReadOnlyList<CategoryOption> Categories,
    IReadOnlyList<GoalOption> Goals,
    IReadOnlyList<StrategyOption> Strategies,
    // The UI has no identity to derive a dealer group from, so the roster comes
    // from here rather than being hardcoded in the bundle.
    IReadOnlyList<string> DealerGroups);

public sealed record SupportPlanRequest(string DealershipId, string Category, string ConcernText, string DealerGroupId);

public sealed record RecommendationResource(string Id, string Label, string Kind);

/// <summary>Dealer-group-scoped evidence pointer surfaced to the UI.</summary>
public sealed record RecommendationCitation(
    string CitationId,
    string DealerGroupId,
    string SourceType,
    string SourceTitle,
    string SectionOrPage,
    string EvidenceSummary,
    string SourceRef,
    string RetrievedAt,
    double Confidence);

/// <summary>
/// Coordinator output, also accepted back on POST /api/supports/plans.
/// </summary>
/// <remarks>
/// The bounds in <see cref="RequestModels"/> are not a substitute for the
/// validator - they cap what a client can persist through the save endpoint,
/// which does not re-run the three-agent pipeline.
/// </remarks>
public sealed record Recommendation(
    string DealerGroupId,
    string DetectedNeed,
    IReadOnlyList<string> EvidenceSummary,
    string Rationale,
    string SupportTier,
    string RecommendedFrequency,
    string GroupingGuidance,
    IReadOnlyList<RecommendationResource> ResourceMatches,
    IReadOnlyList<string> ManagerNextSteps,
    IReadOnlyList<string> ProgressMonitoring,
    int ReviewWindowDays,
    string DecisionRule,
    IReadOnlyList<string> Caveats,
    IReadOnlyList<string> GoalSuggestions,
    IReadOnlyList<string> StrategySuggestions,
    IReadOnlyList<RecommendationCitation> Citations,
    // Each value is a bool or a list of strings, as in the Python model.
    IReadOnlyDictionary<string, object> Completeness,
    string HumanReviewState,
    string GeneratedBy);

/// <summary>
/// Response for POST /api/recommendations/support-plan.
/// </summary>
/// <remarks>
/// <c>status</c> reflects the coordinator outcome. When status != 'ok' the
/// recommendation body is omitted and the UI must render a safe state.
/// </remarks>
public sealed record RecommendationEnvelope
{
    public required string Status { get; init; }
    public string? ErrorCode { get; init; }
    public string? ErrorMessage { get; init; }
    public Recommendation? Recommendation { get; init; }
    public IReadOnlyList<AgentTraceStep> AgentTrace { get; init; } = [];
    public required string ProviderModel { get; init; }
    public required string CorrelationId { get; init; }
    public required string DealerGroupId { get; init; }
    // What the application controls did on this run. `null` means not
    // measured -- the UI must render absence, not zero.
    public int? EvidenceCount { get; init; }
    public int? CitationCount { get; init; }
    public int? CitationsProposed { get; init; }
    public int? CitationsAccepted { get; init; }
    public int? ResourcesProposed { get; init; }
    public int? ResourcesAccepted { get; init; }
    public IReadOnlyList<string> UnknownResourceIds { get; init; } = [];
    public string? ValidatorStatus { get; init; }
    public bool ValidationReached { get; init; }
    public int? Attempts { get; init; }
    public int? DeterministicChecksTotal { get; init; }
}

public sealed record SavedPlan(
    string PlanId,
    string DealershipId,
    string DealerGroupId,
    string Category,
    string ConcernText,
    string? SelectedGoal,
    IReadOnlyList<string> SelectedStrategies,
    string CreatedAt,
    Recommendation Recommendation,
    string HumanReviewState = "draft");

public sealed record SavedPlansResponse(IReadOnlyList<SavedPlan> Plans, int Total);

public sealed record SavePlanRequest(
    string DealershipId,
    string Category,
    string ConcernText,
    string? SelectedGoal,
    IReadOnlyList<string> SelectedStrategies,
    Recommendation Recommendation,
    string DealerGroupId);

/// <summary>Request body for POST /api/supports/plans/{plan_id}/review.</summary>
public sealed record ReviewTransitionRequest(string ToState, string UserLabel = "Staff S-01");

public sealed record AuditEvent
{
    public required string EventId { get; init; }
    public required string Timestamp { get; init; }
    public required string Endpoint { get; init; }
    public required string Context { get; init; }
    public required string User { get; init; }
    public required string ProviderModel { get; init; }
    public required int DurationMs { get; init; }
    public required int TokenEstimate { get; init; }
    public required string Status { get; init; }
    public string CorrelationId { get; init; } = "";
    public string DealerGroupId { get; init; } = "";
    public int EvidenceCount { get; init; }
    public int CitationCount { get; init; }
    public string ValidatorStatus { get; init; } = "";
}

public sealed record AuditResponse(IReadOnlyList<AuditEvent> Events, int Total, string Disclaimer);
