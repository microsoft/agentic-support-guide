using AgenticSupportGuide.Api.Agents.Shared;

namespace AgenticSupportGuide.Api.Workflows;

/// <summary>Everything the workflow needs. Assembled by the HTTP layer.</summary>
public sealed record CoordinatorRequest(
    string DealerGroupId,
    string DealershipLabel,
    string RegionId,
    string Segment,
    double ProcessScore,
    double AppointmentAttendanceRate,
    double FollowupIndex,
    double EngagementIndex,
    AreaSeries AreaSeries,
    OperationsSeries OperationsSeries,
    string Category,
    string ConcernText,
    IReadOnlyList<ResourceRef> AllowedResources,
    IReadOnlyList<string> AllowedGoalIds,
    IReadOnlyList<string> AllowedStrategyIds);

/// <summary>What identifies one run, as opposed to what it has done so far.</summary>
public sealed record RunContext(string CorrelationId, string DealerGroupId, string ProviderModel);

/// <summary>The workflow outcome. <c>Recommendation</c> is null unless status is ok.</summary>
public sealed record CoordinatorResult
{
    public required string Status { get; init; }
    public required string? ErrorCode { get; init; }
    public required string? ErrorMessage { get; init; }
    public required Recommendation? Recommendation { get; init; }
    public required IReadOnlyList<AgentTraceStep> AgentTrace { get; init; }
    public required string ProviderModel { get; init; }
    public required string CorrelationId { get; init; }
    public required string DealerGroupId { get; init; }
    public int? EvidenceCount { get; init; }
    public int? CitationCount { get; init; }
    public string ValidatorStatus { get; init; } = "";
    // Enforcement facts for the UI receipt. Null means the stage never ran, so
    // the UI renders absence. A zero here would assert the stage ran and found
    // nothing, which on a run that died early is a false claim.
    public int? CitationsProposed { get; init; }
    public int? CitationsAccepted { get; init; }
    public int? ResourcesProposed { get; init; }
    public int? ResourcesAccepted { get; init; }
    public IReadOnlyList<string> UnknownResourceIds { get; init; } = [];
    public int? Attempts { get; init; }
    public bool ValidationReached { get; init; }
    public int? DeterministicChecksTotal { get; init; }
}

/// <summary>
/// One trace row as an executor reports it, via <c>YieldOutputAsync</c>.
/// </summary>
/// <remarks>
/// The coordinator adds the duration from the workflow's own executor-invoked
/// and executor-completed events.
/// </remarks>
public sealed record StepRecord(
    string Agent,
    string Status,
    string Provider,
    string Model,
    int? TokenEstimate = null,
    IReadOnlyList<string>? IssueCodes = null,
    IReadOnlyList<string>? WarningCodes = null,
    int CitationCount = 0);

/// <summary>
/// Abort the workflow.
/// </summary>
/// <remarks>
/// Carries the outcome and the plan as far as it got. Agent Framework reports
/// it as the failing executor's error, where the coordinator turns it into a
/// <see cref="CoordinatorResult"/>.
/// </remarks>
public sealed class StepFailedException(string status, string errorCode, string errorMessage, PlanState plan) : Exception(errorCode)
{
    public string Status { get; } = status;

    public string ErrorCode { get; } = errorCode;

    public string ErrorMessage { get; } = errorMessage;

    public PlanState Plan { get; } = plan;
}

public static class Results
{
    // Recorded on trace steps that completed without any model call, so a
    // deterministic step is never credited to a model that did no work.
    public const string LocalStepModel = "none";

    /// <summary>A finished result for a run that ended without a recommendation.</summary>
    public static CoordinatorResult FailureResult(
        RunContext context,
        PlanState? plan,
        IReadOnlyList<AgentTraceStep> trace,
        string status,
        string errorCode,
        string errorMessage,
        string validatorStatus = "") =>
        new()
        {
            Status = status,
            ErrorCode = errorCode,
            ErrorMessage = errorMessage,
            Recommendation = null,
            AgentTrace = trace,
            ProviderModel = context.ProviderModel,
            CorrelationId = context.CorrelationId,
            DealerGroupId = context.DealerGroupId,
            EvidenceCount = plan?.EvidenceCount,
            CitationCount = plan?.CitationCount,
            ValidatorStatus = validatorStatus,
            CitationsProposed = plan?.CitationsProposed,
            CitationsAccepted = plan?.CitationsAccepted,
            Attempts = plan is null || plan.Attempts == 0 ? null : plan.Attempts,
            ValidationReached = plan?.ValidationReached ?? false,
            DeterministicChecksTotal = plan?.DeterministicChecksTotal,
        };
}
