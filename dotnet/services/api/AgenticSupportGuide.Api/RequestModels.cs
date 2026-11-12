using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api;

/// <summary>
/// Request bodies, validated field by field, reporting where each one is wrong.
/// </summary>
/// <remarks>
/// The rules are the Python track's Pydantic request models, applied with
/// Pydantic's semantics (see <see cref="PydanticReader"/>). Errors are dotted
/// paths starting at <c>body</c>, which is what the 422 response's
/// <c>fields</c> lists.
/// </remarks>
public static class RequestModels
{
    private static readonly Regex IdPattern = new(@"^[A-Za-z0-9][A-Za-z0-9\-_]*\z", RegexOptions.CultureInvariant);
    private static readonly Regex DealerGroupPattern = new(@"^[A-Z0-9][A-Z0-9\-]{1,31}\z", RegexOptions.CultureInvariant);
    private static readonly Regex ReviewStatePattern = new(@"^(pending_review|approved|rejected)\z", RegexOptions.CultureInvariant);

    public static SupportPlanRequest? ParseSupportPlanRequest(JsonBody body, List<string> errors)
    {
        if (Root(body, errors) is not { } v)
        {
            return null;
        }
        var dealershipId = v.Str("dealership_id", minLength: 1, maxLength: 64, pattern: IdPattern);
        var category = v.Str("category", minLength: 1, maxLength: 64, pattern: IdPattern);
        var concernText = v.Str("concern_text", minLength: 1, maxLength: 1000);
        var dealerGroupId = v.Str("dealer_group_id", minLength: 2, maxLength: 32, pattern: DealerGroupPattern);
        return v.Failed ? null : new SupportPlanRequest(dealershipId!, category!, concernText!, dealerGroupId!);
    }

    public static SavePlanRequest? ParseSavePlanRequest(JsonBody body, List<string> errors)
    {
        if (Root(body, errors) is not { } v)
        {
            return null;
        }
        var dealershipId = v.Str("dealership_id", minLength: 1, maxLength: 64, pattern: IdPattern);
        var category = v.Str("category", minLength: 1, maxLength: 64, pattern: IdPattern);
        var concernText = v.Str("concern_text", minLength: 1, maxLength: 1000);
        var selectedGoal = v.OptionalStr("selected_goal", maxLength: 64);
        var selectedStrategies = v.StrList("selected_strategies", maxItems: 20, required: false);
        var recommendation = v.Model("recommendation", ParseRecommendation);
        var dealerGroupId = v.Str("dealer_group_id", minLength: 2, maxLength: 32, pattern: DealerGroupPattern);
        if (v.Failed)
        {
            return null;
        }
        // Refuse to persist a plan whose recommendation belongs elsewhere. The
        // save endpoint does not re-run the pipeline, so this is the only place
        // the tenant boundary is re-checked on the way in.
        if (recommendation!.DealerGroupId != dealerGroupId)
        {
            errors.Add("body");
            return null;
        }
        return new SavePlanRequest(dealershipId!, category!, concernText!, selectedGoal, selectedStrategies ?? [], recommendation, dealerGroupId!);
    }

    public static ReviewTransitionRequest? ParseReviewTransitionRequest(JsonBody body, List<string> errors)
    {
        if (Root(body, errors) is not { } v)
        {
            return null;
        }
        var toState = v.Str("to_state", pattern: ReviewStatePattern);
        var userLabel = v.Str("user_label", maxLength: 32, defaultValue: "Staff S-01");
        return v.Failed ? null : new ReviewTransitionRequest(toState!, userLabel!);
    }

    private static Recommendation? ParseRecommendation(PydanticReader v)
    {
        var dealerGroupId = v.Str("dealer_group_id", minLength: 2, maxLength: 32);
        var detectedNeed = v.Str("detected_need", maxLength: 300);
        var evidenceSummary = v.StrList("evidence_summary", maxItems: 20);
        var rationale = v.Str("rationale", maxLength: 2000);
        var supportTier = v.Str("support_tier", maxLength: 60);
        var recommendedFrequency = v.Str("recommended_frequency", maxLength: 120);
        var groupingGuidance = v.Str("grouping_guidance", maxLength: 200);
        var resourceMatches = v.ModelList("resource_matches", ParseResource, maxItems: 20);
        var managerNextSteps = v.StrList("manager_next_steps", maxItems: 20);
        var progressMonitoring = v.StrList("progress_monitoring", maxItems: 20);
        var reviewWindowDays = v.Int("review_window_days", min: 0, max: 365);
        var decisionRule = v.Str("decision_rule", maxLength: 300);
        var caveats = v.StrList("caveats", maxItems: 20);
        var goalSuggestions = v.StrList("goal_suggestions", maxItems: 20);
        var strategySuggestions = v.StrList("strategy_suggestions", maxItems: 20);
        var citations = v.ModelList("citations", ParseCitation, maxItems: 20);
        var completeness = v.BoolOrStrListMap("completeness");
        var humanReviewState = v.Str("human_review_state", maxLength: 40);
        var generatedBy = v.Str("generated_by", maxLength: 300);
        if (v.Failed)
        {
            return null;
        }
        return new Recommendation(
            dealerGroupId!, detectedNeed!, evidenceSummary!, rationale!, supportTier!, recommendedFrequency!,
            groupingGuidance!, resourceMatches!, managerNextSteps!, progressMonitoring!, reviewWindowDays!.Value,
            decisionRule!, caveats!, goalSuggestions!, strategySuggestions!, citations!, completeness!,
            humanReviewState!, generatedBy!);
    }

    private static RecommendationResource? ParseResource(PydanticReader v)
    {
        var id = v.Str("id");
        var label = v.Str("label");
        var kind = v.Str("kind");
        return v.Failed ? null : new RecommendationResource(id!, label!, kind!);
    }

    private static RecommendationCitation? ParseCitation(PydanticReader v)
    {
        var citationId = v.Str("citation_id");
        var dealerGroupId = v.Str("dealer_group_id");
        var sourceType = v.Str("source_type");
        var sourceTitle = v.Str("source_title");
        var sectionOrPage = v.Str("section_or_page", defaultValue: "");
        var evidenceSummary = v.Str("evidence_summary");
        var sourceRef = v.Str("source_ref");
        var retrievedAt = v.Str("retrieved_at");
        var confidence = v.Float("confidence");
        return v.Failed
            ? null
            : new RecommendationCitation(citationId!, dealerGroupId!, sourceType!, sourceTitle!, sectionOrPage!, evidenceSummary!, sourceRef!, retrievedAt!, confidence!.Value);
    }

    // A missing body, a non-JSON body and a JSON body that is not an object
    // are all reported against the body as a whole.
    private static PydanticReader? Root(JsonBody body, List<string> errors)
    {
        if (body.Kind == JsonBody.BodyKind.Parsed && body.Value.ValueKind == System.Text.Json.JsonValueKind.Object)
        {
            return new PydanticReader(body.Value, "body", errors);
        }
        errors.Add("body");
        return null;
    }
}
