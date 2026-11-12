using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Agents.Validator;

/// <summary>
/// What the checks found, in the shape the report needs.
/// </summary>
/// <remarks>
/// Codes and fields are de-duplicated when the report is built, so a check
/// never has to ask whether an earlier check already flagged something.
/// </remarks>
public sealed class Findings
{
    public List<string> IssueCodes { get; } = [];

    public List<string> FailedFields { get; } = [];

    // Carried separately because the repair guidance names the offending ids.
    public List<string> UnknownResourceIds { get; } = [];

    public bool Passed => IssueCodes.Count == 0;

    public void Flag(string code, params string[] fields)
    {
        IssueCodes.Add(code);
        FailedFields.AddRange(fields);
    }
}

/// <summary>
/// The deterministic validator checks.
/// </summary>
/// <remarks>
/// Each check is an independent function that records findings;
/// <see cref="RunChecks"/> applies all of them. Adding a rule means adding a
/// function and listing it in <see cref="DeterministicChecks"/> -- no existing
/// check has to be edited.
///
/// These decide pass/fail. The LLM critique in the validator agent is advisory
/// and can only add warning codes.
/// </remarks>
public static class Checks
{
    public static readonly IReadOnlyList<string> RequiredKeywordCaveats = [Determinations.RequiredReviewPhrase];
    public static readonly IReadOnlyList<string> RequiredTierPatterns = ["baseline", "focused", "intensive", "advanced"];

    // Identifiers carry no prose. Citations are retrieved evidence rather than
    // something this system asserts, and source material legitimately discusses
    // recalls and pricing rules, so scanning them would fail honest answers.
    //
    // Residual risk, accepted: a poisoned source document carrying the requesting
    // dealer_group_id could put a determination on screen inside a citation. It
    // is bounded because the model cannot author citation text -- the
    // recommender substitutes the retriever's stored Citation -- and because each
    // learner owns their own index. Citations are still screened for review
    // denial below.
    public static readonly IReadOnlySet<string> DeterminationScanSkip = new HashSet<string> { "contract_version", "dealer_group_id", "citations" };

    public static readonly IReadOnlyList<Action<ValidatorInput, Findings>> DeterministicChecks =
    [
        CheckContractVersion,
        CheckDealerGroup,
        CheckCatalogMembership,
        CheckCitations,
        CheckCaveats,
        CheckSupportTier,
        CheckRequiredSections,
        CheckForbiddenDeterminations,
    ];

    /// <summary>
    /// Run every check. None of them short-circuit.
    /// </summary>
    /// <remarks>
    /// A draft that fails one rule is still measured against the rest, so a
    /// single repair round can address everything at once.
    /// </remarks>
    public static Findings RunChecks(ValidatorInput payload)
    {
        var findings = new Findings();
        foreach (var check in DeterministicChecks)
        {
            check(payload, findings);
        }
        return findings;
    }

    public static void CheckContractVersion(ValidatorInput payload, Findings findings)
    {
        var required = payload.Context.RequiredContractVersion;
        if (payload.Draft.ContractVersion != required)
        {
            findings.Flag("CONTRACT_VERSION_MISMATCH", "contract_version");
        }
        if (payload.Analysis.ContractVersion != required)
        {
            findings.Flag("CONTRACT_VERSION_MISMATCH");
        }
    }

    public static void CheckDealerGroup(ValidatorInput payload, Findings findings)
    {
        if (payload.Draft.DealerGroupId != payload.Context.DealerGroupId)
        {
            findings.Flag("DRAFT_DEALER_GROUP_MISMATCH", "dealer_group_id");
        }
    }

    /// <summary>The draft may only reference ids the API handed the recommender.</summary>
    public static void CheckCatalogMembership(ValidatorInput payload, Findings findings)
    {
        var allowedResources = payload.Context.AllowedResourceIds.ToHashSet();
        var unknown = payload.Draft.ResourceIds.Where(id => !allowedResources.Contains(id)).ToList();
        if (unknown.Count > 0)
        {
            findings.UnknownResourceIds.AddRange(unknown);
            findings.Flag("UNKNOWN_RESOURCE_ID", "resource_ids");
        }

        var allowedGoals = payload.Context.AllowedGoalIds.ToHashSet();
        if (payload.Draft.GoalSuggestions.Any(id => !allowedGoals.Contains(id)))
        {
            findings.Flag("UNKNOWN_GOAL_ID", "goal_suggestions");
        }

        var allowedStrategies = payload.Context.AllowedStrategyIds.ToHashSet();
        if (payload.Draft.StrategySuggestions.Any(id => !allowedStrategies.Contains(id)))
        {
            findings.Flag("UNKNOWN_STRATEGY_ID", "strategy_suggestions");
        }
    }

    /// <summary>The core evidence-backed requirement.</summary>
    public static void CheckCitations(ValidatorInput payload, Findings findings)
    {
        if (payload.Draft.Citations.Count == 0)
        {
            findings.Flag("MISSING_CITATIONS", "citations");
            return;
        }

        var allowed = payload.Context.AllowedCitationIds.ToHashSet();
        foreach (var citation in payload.Draft.Citations)
        {
            if (citation.DealerGroupId != payload.Context.DealerGroupId)
            {
                findings.Flag("CROSS_DEALER_GROUP_CITATION", "citations");
            }
            if (!allowed.Contains(citation.CitationId))
            {
                findings.Flag("UNKNOWN_CITATION_ID", "citations");
            }
        }
    }

    public static void CheckCaveats(ValidatorInput payload, Findings findings)
    {
        if (payload.Draft.Caveats.Count == 0)
        {
            findings.Flag("MISSING_CAVEATS", "caveats");
            return;
        }
        var caveatText = PyText.Lower(string.Join(" ", payload.Draft.Caveats));
        if (!RequiredKeywordCaveats.All(keyword => caveatText.Contains(keyword, StringComparison.Ordinal)))
        {
            findings.Flag("MISSING_HUMAN_REVIEW_CAVEAT", "caveats");
        }
    }

    public static void CheckSupportTier(ValidatorInput payload, Findings findings)
    {
        var tier = PyText.Lower(payload.Draft.SupportTier);
        if (!RequiredTierPatterns.Any(pattern => tier.Contains(pattern, StringComparison.Ordinal)))
        {
            findings.Flag("INVALID_SUPPORT_TIER", "support_tier");
        }
    }

    public static void CheckRequiredSections(ValidatorInput payload, Findings findings)
    {
        if (payload.Draft.ProgressMonitoring.Count == 0)
        {
            findings.Flag("MISSING_PROGRESS_MONITORING", "progress_monitoring");
        }
        if (payload.Draft.ManagerNextSteps.Count == 0)
        {
            findings.Flag("MISSING_NEXT_STEPS", "manager_next_steps");
        }
        if (PyText.Strip(payload.Draft.Rationale).Length == 0)
        {
            findings.Flag("MISSING_RATIONALE", "rationale");
        }
    }

    /// <summary>Scans every draft field, not a chosen three.</summary>
    public static void CheckForbiddenDeterminations(ValidatorInput payload, Findings findings)
    {
        var offenders = Determinations.OffendingFields(payload.Draft.Fields(), DeterminationScanSkip);
        // The analyst's summary is not part of the draft, but the workflow
        // serves `detected_need` and `evidence_summary` straight from it. Left
        // unscanned, a determination there reached the UI with completeness ok.
        offenders.AddRange(Determinations.OffendingFields(payload.Analysis.Analysis.Fields()).Select(name => $"analysis.{name}"));
        if (offenders.Count > 0)
        {
            findings.Flag("FORBIDDEN_DETERMINATION", [.. offenders]);
        }

        // Citation text is retrieved evidence, so it is not scanned for
        // determinations -- source material discusses them legitimately. A
        // source claiming review can be skipped is never legitimate, though,
        // and that is the shape a poisoned document would take.
        if (payload.Draft.Citations.Any(c => Determinations.DeniesHumanReview(c.EvidenceSummary)))
        {
            findings.Flag("FORBIDDEN_DETERMINATION", "citations");
        }
    }
}
