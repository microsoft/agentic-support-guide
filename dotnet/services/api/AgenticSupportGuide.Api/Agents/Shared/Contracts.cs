using System.Text.Json;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Parity;
using static AgenticSupportGuide.Api.Parity.PydanticReader;

namespace AgenticSupportGuide.Api.Agents.Shared;

/// <summary>
/// Shared, immutable contracts exchanged between agents.
/// </summary>
/// <remarks>
/// These schemas represent a bounded context that could later be extracted
/// into a versioned shared library or schema registry. They intentionally
/// depend on nothing in the agent implementations.
///
/// The constraints are the Python track's Pydantic constraints, enforced with
/// the same semantics, so a model output one track accepts the other accepts.
/// </remarks>
public static class Contracts
{
    public const string ContractVersion = "1.0.0";

    internal static readonly string[] ContractVersions = [ContractVersion];

    internal static readonly StrRule Id = new(MinLength: 1, MaxLength: 60);
    internal static readonly StrRule Bullet = new(MinLength: 1, MaxLength: 300);

    // Citation IDs come from the evidence store, not from the model, and run
    // longer than the resource IDs `Id` covers.
    internal static readonly StrRule CitationId = new(MinLength: 1, MaxLength: 64);

    // Same shape as PromptBlocks.CodeRegex.
    internal static readonly StrRule Code = new(Pattern: new Regex(@"^[A-Z][A-Z0-9_]{3,59}\z", RegexOptions.CultureInvariant));

    // dealer_group_id has strict shape: uppercase letters, digits, and dashes.
    // Kept short so it fits comfortably in trace metadata.
    internal static readonly StrRule DealerGroupId = new(MinLength: 2, MaxLength: 32, Pattern: new Regex(@"^[A-Z0-9][A-Z0-9\-]{1,31}\z", RegexOptions.CultureInvariant));

    // These mirror the caps on `Recommendation` in Models.cs. They must not be
    // looser: a draft the validator approves but the response model rejects
    // fails after the point where a typed refusal can still be returned.
    internal const int NeedMax = 300;
    internal const int TierMax = 60;
    internal const int FrequencyMax = 120;
    internal const int GroupingMax = 200;
    internal const int DecisionRuleMax = 300;
    internal const int LongTextMax = 2000;

    /// <summary>Parse a model's JSON text into a contract, or throw <see cref="ModelOutputException"/>.</summary>
    public static T ParseModelOutput<T>(string text, Func<PydanticReader, T?> parse)
        where T : class
    {
        JsonElement root;
        try
        {
            using var document = JsonDocument.Parse(text);
            root = document.RootElement.Clone();
        }
        catch (JsonException)
        {
            throw new ModelOutputException("invalid_model_json");
        }
        var errors = new List<string>();
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new ModelOutputException("invalid_model_schema");
        }
        var parsed = parse(new PydanticReader(root, "", errors));
        if (parsed is null || errors.Count > 0)
        {
            throw new ModelOutputException("invalid_model_schema");
        }
        return parsed;
    }

    internal static bool Check(string value, StrRule rule)
    {
        var length = PyText.Len(value);
        return !(rule.MinLength is { } min && length < min)
            && !(rule.MaxLength is { } max && length > max)
            && (rule.Pattern is null || rule.Pattern.IsMatch(value));
    }
}

/// <summary>
/// A model's output could not be read as the contract it was asked for.
/// </summary>
/// <remarks>
/// Carries a fixed reason only. The output itself is model text derived from a
/// dealer group's evidence, and it must never reach an exception message, a
/// span, or the response.
/// </remarks>
public sealed class ModelOutputException(string reason) : ArgumentException(reason);

/// <summary>A contract built in code violated its own constraints.</summary>
public sealed class ContractValidationException(string contract) : ArgumentException($"{contract} failed validation");

public sealed record ResourceRef(string Id, string Label, string Kind);

/// <summary>
/// Enumerated source types allowed in a Citation.
/// </summary>
/// <remarks>
/// <c>synthetic_fixture</c> is the only source type produced by this prototype
/// today; the others describe production ambitions.
/// </remarks>
public static class CitationSourceType
{
    public const string StructuredData = "structured_data";
    public const string Document = "document";
    public const string Policy = "policy";
    public const string Resource = "resource";
    public const string SyntheticFixture = "synthetic_fixture";

    public static readonly IReadOnlyList<string> All = [StructuredData, Document, Policy, Resource, SyntheticFixture];
}

/// <summary>
/// Evidence pointer attached to a recommendation.
/// </summary>
/// <remarks>
/// A citation is dealer-group-scoped and safe to log: it never contains prompt
/// text, completion text, real URLs, real document titles, real group names,
/// or real IDs. <c>SourceRef</c> is an opaque token that resolves to a
/// group-specific evidence store; the workflow validates that the
/// <c>DealerGroupId</c> on the citation matches the request.
/// </remarks>
public sealed record Citation(
    string CitationId,
    string DealerGroupId,
    string SourceType,
    string SourceTitle,
    string SectionOrPage,
    string EvidenceSummary,
    string SourceRef,
    string RetrievedAt,
    double Confidence)
{
    /// <summary>Every field within its constraints.</summary>
    public bool IsValid() =>
        Contracts.Check(CitationId, Contracts.CitationId)
        && Contracts.Check(DealerGroupId, Contracts.DealerGroupId)
        && CitationSourceType.All.Contains(SourceType)
        && Contracts.Check(SourceTitle, new StrRule(1, 200))
        && Contracts.Check(SectionOrPage, new StrRule(MaxLength: 80))
        && Contracts.Check(EvidenceSummary, new StrRule(1, 500))
        && Contracts.Check(SourceRef, new StrRule(1, 200))
        && Contracts.Check(RetrievedAt, new StrRule(1, 32))
        && Confidence >= 0.0 && Confidence <= 1.0;
}

public sealed record AnalysisSummary(
    string DetectedNeed,
    IReadOnlyList<string> EvidenceBullets,
    IReadOnlyList<string> MissingDataFlags,
    double AnalysisConfidence)
{
    /// <summary>The fields scanned for determinations, in declaration order.</summary>
    public IEnumerable<(string Name, object Value)> Fields()
    {
        yield return ("detected_need", DetectedNeed);
        yield return ("evidence_bullets", EvidenceBullets);
        yield return ("missing_data_flags", MissingDataFlags);
        yield return ("analysis_confidence", AnalysisConfidence);
    }
    internal static AnalysisSummary? Parse(PydanticReader v)
    {
        var detectedNeed = v.Str("detected_need", maxLength: Contracts.NeedMax);
        var evidenceBullets = v.StrList("evidence_bullets", maxItems: 12, item: Contracts.Bullet, required: false);
        var missingDataFlags = v.StrList("missing_data_flags", maxItems: 8, item: Contracts.Bullet, required: false);
        var confidence = v.Float("analysis_confidence", min: 0.0, max: 1.0);
        return v.Failed ? null : new AnalysisSummary(detectedNeed!, evidenceBullets!, missingDataFlags!, confidence!.Value);
    }
}

public sealed record DataAnalystOutput(
    string ContractVersion,
    string DealerGroupId,
    AnalysisSummary Analysis,
    IReadOnlyList<Citation> Citations)
{
    /// <summary>Built in code, validated as Pydantic validates on construction.</summary>
    public static DataAnalystOutput Create(string contractVersion, string dealerGroupId, AnalysisSummary analysis)
    {
        if (contractVersion != Contracts.ContractVersion || !Contracts.Check(dealerGroupId, Contracts.DealerGroupId))
        {
            throw new ContractValidationException(nameof(DataAnalystOutput));
        }
        return new DataAnalystOutput(contractVersion, dealerGroupId, analysis, []);
    }
}

public sealed record SupportRecommendationDraft(
    string ContractVersion,
    string DealerGroupId,
    string DetectedNeed,
    string SupportTier,
    string RecommendedFrequency,
    string GroupingGuidance,
    IReadOnlyList<string> ResourceIds,
    string Rationale,
    IReadOnlyList<string> GoalSuggestions,
    IReadOnlyList<string> StrategySuggestions,
    IReadOnlyList<string> ManagerNextSteps,
    IReadOnlyList<string> ProgressMonitoring,
    int ReviewWindowDays,
    string DecisionRule,
    IReadOnlyList<string> Caveats,
    IReadOnlyList<Citation> Citations)
{
    /// <summary>The fields scanned for determinations, in declaration order.</summary>
    public IEnumerable<(string Name, object Value)> Fields()
    {
        yield return ("contract_version", ContractVersion);
        yield return ("dealer_group_id", DealerGroupId);
        yield return ("detected_need", DetectedNeed);
        yield return ("support_tier", SupportTier);
        yield return ("recommended_frequency", RecommendedFrequency);
        yield return ("grouping_guidance", GroupingGuidance);
        yield return ("resource_ids", ResourceIds);
        yield return ("rationale", Rationale);
        yield return ("goal_suggestions", GoalSuggestions);
        yield return ("strategy_suggestions", StrategySuggestions);
        yield return ("manager_next_steps", ManagerNextSteps);
        yield return ("progress_monitoring", ProgressMonitoring);
        yield return ("review_window_days", ReviewWindowDays);
        yield return ("decision_rule", DecisionRule);
        yield return ("caveats", Caveats);
        yield return ("citations", Citations);
    }
}

public sealed record ValidatorReport(
    string ContractVersion,
    string DealerGroupId,
    bool Passed,
    IReadOnlyList<string> IssueCodes,
    IReadOnlyList<string> WarningCodes,
    IReadOnlyList<string> FailedFields,
    string SafeSummary,
    string RepairGuidance)
{
    /// <summary>Built in code, validated as Pydantic validates on construction.</summary>
    public static ValidatorReport Create(
        string dealerGroupId,
        bool passed,
        IReadOnlyList<string> issueCodes,
        IReadOnlyList<string> warningCodes,
        IReadOnlyList<string> failedFields,
        string safeSummary,
        string repairGuidance)
    {
        var valid = Contracts.Check(dealerGroupId, Contracts.DealerGroupId)
            && issueCodes.Count <= 20 && issueCodes.All(c => Contracts.Check(c, Contracts.Code))
            && warningCodes.Count <= 20 && warningCodes.All(c => Contracts.Check(c, Contracts.Code))
            && failedFields.Count <= 20 && failedFields.All(f => Contracts.Check(f, Contracts.Id))
            && PyText.Len(safeSummary) <= 500
            && PyText.Len(repairGuidance) <= 1000;
        if (!valid)
        {
            throw new ContractValidationException(nameof(ValidatorReport));
        }
        return new ValidatorReport(Contracts.ContractVersion, dealerGroupId, passed, issueCodes, warningCodes, failedFields, safeSummary, repairGuidance);
    }
}

// --- Model-facing output shapes -------------------------------------------
// These are what the LLM is asked to emit, and what the structured-output
// response format targets. They deliberately omit fields the workflow injects
// from trusted context (dealer_group_id above all), which the model has no way
// to know.

public sealed record DataAnalystModelOutput(string ContractVersion, AnalysisSummary Analysis)
{
    public static DataAnalystModelOutput? Parse(PydanticReader v)
    {
        var contractVersion = v.OneOf("contract_version", Contracts.ContractVersions, defaultValue: Contracts.ContractVersion);
        var analysis = v.Model("analysis", AnalysisSummary.Parse);
        return v.Failed ? null : new DataAnalystModelOutput(contractVersion!, analysis!);
    }
}

public sealed record SupportRecommendationModelOutput(
    string ContractVersion,
    string DetectedNeed,
    string SupportTier,
    string RecommendedFrequency,
    string GroupingGuidance,
    IReadOnlyList<string> ResourceIds,
    string Rationale,
    IReadOnlyList<string> GoalSuggestions,
    IReadOnlyList<string> StrategySuggestions,
    IReadOnlyList<string> ManagerNextSteps,
    IReadOnlyList<string> ProgressMonitoring,
    int ReviewWindowDays,
    string DecisionRule,
    IReadOnlyList<string> Caveats,
    // IDs only. The wrapper resolves them against the group-scoped evidence
    // bundle, so the model cannot fabricate citation text.
    IReadOnlyList<string> CitedIds)
{
    public static SupportRecommendationModelOutput? Parse(PydanticReader v)
    {
        var contractVersion = v.OneOf("contract_version", Contracts.ContractVersions, defaultValue: Contracts.ContractVersion);
        var detectedNeed = v.Str("detected_need", maxLength: Contracts.NeedMax);
        var supportTier = v.Str("support_tier", maxLength: Contracts.TierMax);
        var recommendedFrequency = v.Str("recommended_frequency", maxLength: Contracts.FrequencyMax);
        var groupingGuidance = v.Str("grouping_guidance", maxLength: Contracts.GroupingMax);
        var resourceIds = v.StrList("resource_ids", maxItems: 8, item: Contracts.Id, required: false);
        var rationale = v.Str("rationale", maxLength: Contracts.LongTextMax);
        var goalSuggestions = v.StrList("goal_suggestions", maxItems: 6, item: Contracts.Id, required: false);
        var strategySuggestions = v.StrList("strategy_suggestions", maxItems: 8, item: Contracts.Id, required: false);
        var managerNextSteps = v.StrList("manager_next_steps", maxItems: 8, item: Contracts.Bullet, required: false);
        var progressMonitoring = v.StrList("progress_monitoring", maxItems: 8, item: Contracts.Bullet, required: false);
        var reviewWindowDays = v.Int("review_window_days", min: 7, max: 180);
        var decisionRule = v.Str("decision_rule", maxLength: Contracts.DecisionRuleMax);
        var caveats = v.StrList("caveats", maxItems: 8, item: Contracts.Bullet, required: false);
        var citedIds = v.StrList("cited_ids", maxItems: 12, item: Contracts.CitationId, required: false);
        return v.Failed
            ? null
            : new SupportRecommendationModelOutput(
                contractVersion!, detectedNeed!, supportTier!, recommendedFrequency!, groupingGuidance!, resourceIds!,
                rationale!, goalSuggestions!, strategySuggestions!, managerNextSteps!, progressMonitoring!,
                reviewWindowDays!.Value, decisionRule!, caveats!, citedIds!);
    }
}

/// <summary>
/// Advisory-only critique. The deterministic checks own pass/fail.
/// </summary>
/// <remarks>
/// <c>WarningCodes</c> is deliberately untyped free text: this is raw model
/// output, and <c>EnforceCode</c> drops anything off-format afterwards. Making
/// the field strict turns one malformed advisory code into a failed run.
/// </remarks>
public sealed record ValidatorCritiqueModelOutput(IReadOnlyList<string> WarningCodes, string RepairGuidance)
{
    public static ValidatorCritiqueModelOutput? Parse(PydanticReader v)
    {
        var warningCodes = v.StrList("warning_codes", maxItems: 20, required: false);
        var repairGuidance = v.Str("repair_guidance", maxLength: 1000, defaultValue: "");
        return v.Failed ? null : new ValidatorCritiqueModelOutput(warningCodes!, repairGuidance!);
    }
}
