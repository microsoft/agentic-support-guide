using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Evidence;

namespace AgenticSupportGuide.Api.Workflows;

/// <summary>
/// One request's progress through the graph: what travels the edges.
/// </summary>
/// <remarks>
/// Immutable, and carrying domain data only. Two reasons, both learned the
/// hard way:
///
/// - Several outgoing edges are handed the *same* message object and evaluate
///   their conditions independently. A step that mutates it can make a sibling
///   condition fire that should not, so one run yields two results.
/// - Executor lifecycle events carry the values that pass through them. A
///   service client or a request object in here would travel with them, and
///   prompt text would reach spans that are meant to stay metadata-only.
///
/// Everything that is not domain data -- the runtime, the request, the
/// retriever -- is held on the executors instead, which are built fresh per
/// request.
///
/// The optional fields are filled in by the node that produces them. The
/// <c>Require*</c> accessors exist because the graph guarantees the order --
/// nothing reaches <c>Validate</c> without a draft -- but the compiler cannot
/// see that through the edges.
///
/// The counters are the enforcement receipt. Null means the stage never ran,
/// so the UI renders absence; a zero would claim the stage ran and found
/// nothing, which on a run that died early is false.
/// </remarks>
public sealed record PlanState(string Concern)
{
    public EvidenceBundle? Evidence { get; init; }
    public DataAnalystOutput? Analysis { get; init; }
    public SupportRecommendationDraft? Draft { get; init; }
    public ValidatorReport? Report { get; init; }
    public int Attempts { get; init; }
    public int? EvidenceCount { get; init; }
    public int? CitationCount { get; init; }
    public int? CitationsProposed { get; init; }
    public int? CitationsAccepted { get; init; }
    public bool ValidationReached { get; init; }
    public int? DeterministicChecksTotal { get; init; }

    public EvidenceBundle RequireEvidence() => Required(Evidence, "evidence");

    public DataAnalystOutput RequireAnalysis() => Required(Analysis, "analysis");

    public SupportRecommendationDraft RequireDraft() => Required(Draft, "draft");

    public ValidatorReport RequireReport() => Required(Report, "report");

    private static T Required<T>(T? value, string name)
        where T : class =>
        value ?? throw new InvalidOperationException($"plan reached a node without {name}; the graph is mis-wired");
}

/// <summary>The edge conditions out of the validator.</summary>
public static class Plan
{
    // One repair attempt. The second failure is a refusal, not a third try.
    public const int MaxRecommenderAttempts = 2;

    /// <summary>Edge condition: the validator accepted the draft.</summary>
    public static bool Passed(PlanState? state) => state?.Report is { Passed: true };

    /// <summary>Edge condition: rejected, and a repair attempt is still available.</summary>
    public static bool NeedsRepair(PlanState? state) =>
        state?.Report is { Passed: false } && state.Attempts < MaxRecommenderAttempts;

    /// <summary>Edge condition: rejected again. No recommendation is returned.</summary>
    public static bool RepairExhausted(PlanState? state) =>
        state?.Report is { Passed: false } && state.Attempts >= MaxRecommenderAttempts;
}
