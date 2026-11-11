namespace AgenticSupportGuide.Api;

/// <summary>
/// Human review state model.
/// </summary>
/// <remarks>
/// Recommendations flow through a small state machine before they are acted
/// on. This type owns the states, the allowed transitions, and the
/// audit-record shape emitted on each transition.
/// </remarks>
public static class HumanReview
{
    public const string Draft = "draft";
    public const string PendingReview = "pending_review";
    public const string Approved = "approved";
    public const string Rejected = "rejected";

    public static readonly IReadOnlyList<string> States = [Draft, PendingReview, Approved, Rejected];

    private static readonly Dictionary<string, HashSet<string>> AllowedTransitions = new()
    {
        [Draft] = [PendingReview],
        [PendingReview] = [Approved, Rejected],
        [Approved] = [],
        [Rejected] = [PendingReview],
    };

    public static bool CanTransition(string fromState, string toState) => AllowedTransitions[fromState].Contains(toState);

    public static string Transition(string fromState, string toState)
    {
        if (!CanTransition(fromState, toState))
        {
            throw new InvalidReviewTransitionException($"illegal review transition: {fromState} -> {toState}");
        }
        return toState;
    }
}

/// <summary>Raised when a caller attempts an illegal state transition.</summary>
public sealed class InvalidReviewTransitionException(string message) : ArgumentException(message);

/// <summary>
/// Safe metadata for a review-state transition audit row.
/// </summary>
/// <remarks>Never carries prompts, completions, raw concern text, or secrets.</remarks>
public sealed record ReviewTransitionAuditEntry(
    string CorrelationId,
    string DealerGroupId,
    string UserLabel,
    string Timestamp,
    string PreviousState,
    string NewState,
    string ValidatorVerdict,
    int EvidenceCount);
