using System.Diagnostics;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Workflows;

namespace AgenticSupportGuide.Api;

/// <summary>Endpoint metadata: this route requires the API key.</summary>
public sealed class ApiKeyRequired
{
    public static readonly ApiKeyRequired Instance = new();
}

/// <summary>
/// The HTTP routes, grouped as the Python track's routers are: health,
/// insights, supports, plans and audit.
/// </summary>
/// <remarks>
/// <c>/api/health</c> is the only anonymous route: deploy-app.ps1 and CI poll
/// it to find out which build is serving, and that runs before the web tier is
/// up. Everything else, including <c>/health/details</c>, needs the key; a
/// test walks the route table to prove it.
/// </remarks>
public static class Endpoints
{
    // Audit trail: seeded synthetic rows plus this process's real call metadata.
    public const string AuditDisclaimer =
        "Seeded synthetic rows plus in-memory metadata for LLM calls made during "
        + "the current process. No prompts, completions, raw validator critique, or "
        + "secrets are stored.";

    public static void Map(WebApplication app)
    {
        app.MapGet("/api/health", (AppServices services) => Http.Json(Health(services)));

        Guarded(app.MapGet("/api/health/details", (AppServices services) => Http.Json(Diagnostics.BuildHealthDetails(
            services.Settings, services.Runtime, services.EvidenceRetriever, Config.ServiceName, Config.ServiceVersion))));
        Guarded(app.MapPost("/api/demo/reset", DemoReset));

        // Read-only views over the synthetic dataset. The roster has no dealer
        // group dimension, so these endpoints have nothing to filter on and
        // every caller sees the same network. They still require a key.
        // Tracked in docs/security-and-privacy.md.
        Guarded(app.MapGet("/api/dashboard/summary", (AppServices s) =>
            Http.Json(Dashboard.BuildSummary(s.Repos.Dealerships, s.Repos.AreaScores, s.Repos.Operations))));
        Guarded(app.MapGet("/api/dealerships", (AppServices s) => Http.Json(Dealerships.ListDealershipSummaries(s.Repos.Dealerships))));
        Guarded(app.MapGet("/api/scores/summary", (HttpRequest request, AppServices s) =>
            Http.Json(Scores.Summarize(s.Repos.AreaScores, Query(request, "region"), Query(request, "process_area"), Query(request, "segment")))));
        Guarded(app.MapGet("/api/operations/summary", (AppServices s) => Http.Json(Operations.Summarize(s.Repos.Operations))));

        Guarded(app.MapGet("/api/supports/options", (AppServices s) =>
            Http.Json(Supports.BuildSupportOptions(s.Repos.Dealerships.Select(d => (d.DealershipId, d.DisplayLabel)), DealerGroups.KnownDealerGroups))));
        Guarded(app.MapPost("/api/recommendations/support-plan", PostRecommendation)).WithMetadata(JsonBody.Marker);

        Guarded(app.MapGet("/api/supports/plans", (AppServices s) =>
        {
            var rows = s.PlansStore.List();
            return Http.Json(new SavedPlansResponse(rows, rows.Count));
        }));
        Guarded(app.MapPost("/api/supports/plans", PostSavedPlan)).WithMetadata(JsonBody.Marker);
        Guarded(app.MapPost("/api/supports/plans/{plan_id}/review", PostPlanReview)).WithMetadata(JsonBody.Marker);

        Guarded(app.MapGet("/api/audit/events", (AppServices s) =>
        {
            var combined = Audit.ListEvents(s.Repos.Audit).Concat(s.RuntimeAudit.Snapshot()).ToList();
            return Http.Json(new AuditResponse(combined, combined.Count, AuditDisclaimer));
        }));
    }

    private static RouteHandlerBuilder Guarded(RouteHandlerBuilder route) =>
        route.AddEndpointFilter<ApiKeyFilter>().WithMetadata(ApiKeyRequired.Instance);

    // A repeated query parameter keeps its last value, as Starlette reads it.
    private static string? Query(HttpRequest request, string name) =>
        request.Query.TryGetValue(name, out var values) && values.Count > 0 ? values[^1] : null;

    private static HealthResponse Health(AppServices services) =>
        new(
            Status: "ok",
            Service: Config.ServiceName,
            Version: Config.ServiceVersion,
            Banner: Config.PrototypeBanner,
            ProviderConfigured: services.Settings.Configured,
            FoundryAuthMode: services.Settings.AuthMode,
            BuildId: BuildInfo.CurrentBuildId());

    private static IResult DemoReset(AppServices services)
    {
        if (!services.Settings.DemoResetEnabled)
        {
            return Http.Detail(403, "Demo reset is disabled. Set DEMO_RESET_ENABLED=true to enable (development use only).");
        }
        var auditRemoved = services.RuntimeAudit.Clear();
        var plansRemoved = services.PlansStore.Clear();
        services.PlansStore.Seed(services.Repos.SeededPlans, services.Repos.Dealerships);
        return Http.Json(new DemoResetResponse("ok", plansRemoved, auditRemoved));
    }

    /// <summary>
    /// The route that runs the agent workflow.
    /// </summary>
    /// <remarks>
    /// Resolves the dealership, widens the HTTP request into a
    /// <see cref="CoordinatorRequest"/>, and records the outcome. The
    /// orchestration itself -- who is called, in what order, and what happens
    /// when a step fails -- lives in <see cref="AgentCoordinator"/>.
    /// </remarks>
    private static async Task<IResult> PostRecommendation(HttpContext http, AppServices services)
    {
        var errors = new List<string>();
        if (RequestModels.ParseSupportPlanRequest(JsonBody.Of(http), errors) is not { } payload)
        {
            return Http.ValidationFailed(errors);
        }
        var repos = services.Repos;
        var dealership = repos.Dealerships.FirstOrDefault(d => d.DealershipId == payload.DealershipId);
        if (dealership is null)
        {
            return Http.Detail(404, "Unknown dealership_id");
        }
        // Retrieval is already exact-match scoped, so an unknown group returns an
        // empty bundle and the run fails as evidence_missing after two model
        // calls. Rejecting it here makes the boundary explicit and free.
        if (!DealerGroups.KnownDealerGroups.Contains(payload.DealerGroupId))
        {
            return Http.Detail(404, "Unknown dealer_group_id");
        }

        if (services.Runtime is not { } runtime)
        {
            return Http.Json(new RecommendationEnvelope
            {
                Status = "provider_missing",
                ErrorCode = "AGENT_PROVIDER_MISSING",
                ErrorMessage = $"Microsoft Foundry Agent Service is not configured or bindings are missing. Run {Track.ValidateAgentDefinitions}.",
                Recommendation = null,
                AgentTrace = [],
                ProviderModel = Config.ProviderDisplayUnconfigured,
                CorrelationId = "",
                DealerGroupId = payload.DealerGroupId,
            });
        }

        var coordinator = new AgentCoordinator(runtime, services.EvidenceRetriever, Config.ProviderDisplayConfigured);
        var request = CoordinatorRequestFor(payload, dealership, repos);
        // Timed around the workflow only, so the audited duration stays
        // comparable to the sum of the step durations in the trace.
        var started = Stopwatch.GetTimestamp();
        var result = await coordinator.RunAsync(request, http.RequestAborted);

        services.RuntimeAudit.Append(
            endpoint: "/api/recommendations/support-plan",
            context: "plan-generation",
            providerModel: result.ProviderModel,
            durationMs: (int)Stopwatch.GetElapsedTime(started).TotalMilliseconds,
            tokenEstimate: result.AgentTrace.Sum(step => step.TokenEstimate ?? 0),
            status: result.Status,
            correlationId: result.CorrelationId,
            dealerGroupId: result.DealerGroupId,
            // The audit row is a fixed-shape record, so an unreached stage is
            // written as zero here. The envelope keeps the null the UI needs.
            evidenceCount: result.EvidenceCount ?? 0,
            citationCount: result.CitationCount ?? 0,
            validatorStatus: result.ValidatorStatus);
        return Http.Json(new RecommendationEnvelope
        {
            Status = result.Status,
            ErrorCode = result.ErrorCode,
            ErrorMessage = result.ErrorMessage,
            Recommendation = result.Recommendation,
            AgentTrace = result.AgentTrace,
            ProviderModel = result.ProviderModel,
            CorrelationId = result.CorrelationId,
            DealerGroupId = result.DealerGroupId,
            EvidenceCount = result.EvidenceCount,
            CitationCount = result.CitationCount,
            CitationsProposed = result.CitationsProposed,
            CitationsAccepted = result.CitationsAccepted,
            ResourcesProposed = result.ResourcesProposed,
            ResourcesAccepted = result.ResourcesAccepted,
            UnknownResourceIds = result.UnknownResourceIds,
            ValidatorStatus = result.ValidatorStatus,
            ValidationReached = result.ValidationReached,
            Attempts = result.Attempts,
            DeterministicChecksTotal = result.DeterministicChecksTotal,
        });
    }

    /// <summary>
    /// Widen the HTTP request into everything the workflow needs.
    /// </summary>
    /// <remarks>
    /// The allowed catalogs are resolved here, not by the model: the
    /// recommender may only cite IDs this function hands it.
    /// </remarks>
    private static CoordinatorRequest CoordinatorRequestFor(SupportPlanRequest payload, Dealership dealership, Repositories repos)
    {
        var options = Supports.BuildSupportOptions(repos.Dealerships.Select(d => (d.DealershipId, d.DisplayLabel)), DealerGroups.KnownDealerGroups);
        return new CoordinatorRequest(
            DealerGroupId: payload.DealerGroupId,
            DealershipLabel: dealership.DisplayLabel,
            RegionId: dealership.RegionId,
            Segment: dealership.Segment,
            ProcessScore: dealership.ProcessScore,
            AppointmentAttendanceRate: dealership.AppointmentAttendanceRate,
            FollowupIndex: dealership.FollowupIndex,
            EngagementIndex: dealership.EngagementIndex,
            AreaSeries: Scores.SeriesFor(repos.AreaScores, dealership.DealershipId),
            OperationsSeries: Operations.SeriesFor(repos.Operations, dealership.DealershipId),
            Category: payload.Category,
            ConcernText: payload.ConcernText,
            AllowedResources: repos.Resources.Select(r => new ResourceRef(r.ResourceId, r.Label, r.Kind)).ToList(),
            AllowedGoalIds: options.Goals.Where(g => g.CategoryId == payload.Category).Select(g => g.Id).ToList(),
            AllowedStrategyIds: options.Strategies.Where(s => s.CategoryId == payload.Category).Select(s => s.Id).ToList());
    }

    // Saving plans and moving them through human review. These routes never
    // touch a model: they are storage and state transitions over plans a person
    // already generated.

    private static IResult PostSavedPlan(HttpContext http, AppServices services)
    {
        var errors = new List<string>();
        if (RequestModels.ParseSavePlanRequest(JsonBody.Of(http), errors) is not { } payload)
        {
            return Http.ValidationFailed(errors);
        }
        // The request model only proves the body agrees with itself: both the
        // request and the embedded recommendation could name a group that does
        // not exist.
        if (!DealerGroups.KnownDealerGroups.Contains(payload.DealerGroupId))
        {
            return Http.Detail(404, "Unknown dealer_group_id");
        }
        var plan = new SavedPlan(
            PlanId: services.PlansStore.NextPlanId(),
            DealershipId: payload.DealershipId,
            DealerGroupId: payload.DealerGroupId,
            Category: payload.Category,
            ConcernText: payload.ConcernText,
            SelectedGoal: payload.SelectedGoal,
            SelectedStrategies: payload.SelectedStrategies,
            // Wall-clock time, because these events actually happen now. Seeded
            // demo rows are dated from BaseTimestamp so they stay deterministic.
            CreatedAt: Audit.UtcNowIso(),
            Recommendation: payload.Recommendation,
            HumanReviewState: HumanReview.PendingReview);
        return Http.Json(services.PlansStore.Add(plan));
    }

    private static IResult PostPlanReview(HttpContext http, string plan_id, AppServices services)
    {
        var errors = new List<string>();
        if (RequestModels.ParseReviewTransitionRequest(JsonBody.Of(http), errors) is not { } payload)
        {
            return Http.ValidationFailed(errors);
        }
        var plan = services.PlansStore.Get(plan_id);
        if (plan is null)
        {
            return Http.Detail(404, "Unknown plan_id");
        }
        string newState;
        try
        {
            newState = HumanReview.Transition(plan.HumanReviewState, payload.ToState);
        }
        catch (InvalidReviewTransitionException exc)
        {
            return Http.Detail(409, exc.Message);
        }

        var updated = plan with { HumanReviewState = newState };
        services.PlansStore.Replace(updated);
        services.RuntimeAudit.AppendReviewTransition(new ReviewTransitionAuditEntry(
            // A review happens long after the run, so the run's correlation id is
            // gone. This row correlates on the plan id instead.
            CorrelationId: plan_id,
            DealerGroupId: plan.DealerGroupId,
            // No caller identity exists, so attribution is honest about that
            // rather than recording a name the body supplied.
            UserLabel: "web-tier",
            Timestamp: Audit.UtcNowIso(),
            PreviousState: plan.HumanReviewState,
            NewState: newState,
            ValidatorVerdict: "post-hoc",
            EvidenceCount: plan.Recommendation.Citations.Count));
        return Http.Json(updated);
    }
}
