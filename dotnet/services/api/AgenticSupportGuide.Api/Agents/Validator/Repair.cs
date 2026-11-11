using AgenticSupportGuide.Api.Agents.Shared;

namespace AgenticSupportGuide.Api.Agents.Validator;

/// <summary>What the validator is given to check against.</summary>
public sealed record ValidatorContext(
    string DealerGroupId,
    IReadOnlyList<string> AllowedResourceIds,
    IReadOnlyList<string> AllowedGoalIds,
    IReadOnlyList<string> AllowedStrategyIds,
    IReadOnlyList<string> AllowedCitationIds,
    string RequiredContractVersion);

public sealed record ValidatorInput(DataAnalystOutput Analysis, SupportRecommendationDraft Draft, ValidatorContext Context);

/// <summary>
/// Repair guidance and the safe failure summary.
/// </summary>
/// <remarks>
/// Both are built from fixed templates. Raw model critique never reaches the
/// UI or the audit trail, so nothing here is model-authored.
/// </remarks>
public static class Repair
{
    public const int MaxGuidanceChars = 1000;
    public const int MaxSummaryCodes = 6;

    private static readonly Dictionary<string, string> RepairTemplates = new()
    {
        ["UNKNOWN_RESOURCE_ID"] = "Only reference resource ids from the allowed_ids block. Remove any invented ids.",
        ["UNKNOWN_GOAL_ID"] = "Only reference goal ids from the allowed_ids block.",
        ["UNKNOWN_STRATEGY_ID"] = "Only reference strategy ids from the allowed_ids block.",
        ["MISSING_CITATIONS"] = "Cite at least one citation from the group_evidence block. Recommendations without evidence are rejected.",
        ["CROSS_DEALER_GROUP_CITATION"] = "Every citation.dealer_group_id must match the request dealer_group_id. Remove or replace any cross-group citations.",
        ["UNKNOWN_CITATION_ID"] = "Only cite citation_ids present in the group_evidence block.",
        ["DRAFT_DEALER_GROUP_MISMATCH"] = "The draft dealer_group_id must match the request dealer_group_id.",
        ["MISSING_CAVEATS"] = "Add caveats that require human review before any use.",
        ["MISSING_HUMAN_REVIEW_CAVEAT"] = "Include an explicit 'human review is required' caveat.",
        ["INVALID_SUPPORT_TIER"] = "Support tier must reflect baseline, focused, intensive, or advanced framing.",
        ["MISSING_PROGRESS_MONITORING"] = "Add at least one progress-monitoring measure.",
        ["MISSING_NEXT_STEPS"] = "Add at least one manager next step.",
        ["MISSING_RATIONALE"] = "Provide a non-empty rationale grounded in the analyst evidence.",
        ["CONTRACT_VERSION_MISMATCH"] = "Set contract_version to the required value.",
        ["FORBIDDEN_DETERMINATION"] = "Remove any pricing, credit, compliance, safety, or individual staffing determination language.",
    };

    // A rule lives in two places: the check that emits the code, and the
    // template that tells the recommender how to fix it. A test asserts the two
    // sets agree, because a code with no template silently produces repair
    // guidance that omits the very thing that failed.
    public static readonly IReadOnlySet<string> RepairableIssueCodes = RepairTemplates.Keys.ToHashSet();

    public static string BuildRepairGuidance(IReadOnlyList<string> codes, IReadOnlyList<string> unknownResourceIds)
    {
        if (codes.Count == 0)
        {
            return "";
        }
        var lines = codes
            .Distinct()
            .Order(StringComparer.Ordinal)
            .Where(RepairTemplates.ContainsKey)
            .Select(code => $"- {RepairTemplates[code]}")
            .ToList();
        if (unknownResourceIds.Count > 0)
        {
            lines.Add($"- Unknown resource ids: {Parity.PyText.ReprList(unknownResourceIds.Order(StringComparer.Ordinal).Take(5))}");
        }
        return Parity.PyText.Head(string.Join("\n", lines), MaxGuidanceChars);
    }

    /// <summary>Names the codes only. Never echoes model text or draft content.</summary>
    public static string SafeSummary(bool passed, IReadOnlyList<string> issueCodes)
    {
        if (passed)
        {
            return "Validator passed all deterministic checks.";
        }
        if (issueCodes.Count == 0)
        {
            return "Validator failed with no coded reason.";
        }
        var joined = string.Join(", ", issueCodes.Take(MaxSummaryCodes));
        if (issueCodes.Count > MaxSummaryCodes)
        {
            joined += $", +{issueCodes.Count - MaxSummaryCodes} more";
        }
        return $"Validator failed on: {joined}.";
    }
}
