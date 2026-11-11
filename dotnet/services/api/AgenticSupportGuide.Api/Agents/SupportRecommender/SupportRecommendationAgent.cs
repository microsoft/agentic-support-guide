using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Agents.SupportRecommender;

public sealed record SupportRecommenderContext(
    string DealerGroupId,
    string Category,
    string ConcernText,
    IReadOnlyList<ResourceRef> AllowedResources,
    IReadOnlyList<string> AllowedGoalIds,
    IReadOnlyList<string> AllowedStrategyIds,
    EvidenceBundle Evidence);

/// <summary>
/// A draft plus what the citation substitution actually did.
/// </summary>
/// <remarks>
/// <c>CitationsProposed</c> is not recoverable downstream: the substitution
/// removes the model's own id list before the draft leaves this type.
/// </remarks>
public sealed record DraftResult(SupportRecommendationDraft Draft, int CitationsProposed, int CitationsAccepted, RoleResponse? Call = null);

/// <summary>
/// Support Recommendation Agent - remote Foundry agent invocation.
/// </summary>
/// <remarks>
/// Workflow-supplied group-scoped evidence is:
/// - passed to the remote agent as an untrusted <c>allowed_citations</c> block
///   so the agent can decide which citations support its draft,
/// - also attached to the returned draft by this wrapper, filtered to the
///   citation IDs the remote agent selected.
///
/// If the remote agent selects no citations, the draft's citations are empty
/// and the Validator Agent will fail the draft.
/// </remarks>
public sealed class SupportRecommendationAgent(MafAgentRuntime runtime)
{
    public const string AgentId = "support-recommender";
    public const string AgentName = "support-recommendation-agent";

    public async Task<DraftResult> RecommendWithCountsAsync(
        DataAnalystOutput analysis,
        SupportRecommenderContext context,
        string repairGuidance = "",
        CancellationToken cancellationToken = default)
    {
        var response = await runtime.InvokeAsync(AgentName, BuildPrompt(analysis, context, repairGuidance), typeof(SupportRecommendationModelOutput), cancellationToken);
        var output = Responses.ParseRoleResponse(response, SupportRecommendationModelOutput.Parse);
        return AttachCitations(output, context) with { Call = response };
    }

    public async Task<SupportRecommendationDraft> RecommendAsync(
        DataAnalystOutput analysis,
        SupportRecommenderContext context,
        string repairGuidance = "",
        CancellationToken cancellationToken = default) =>
        (await RecommendWithCountsAsync(analysis, context, repairGuidance, cancellationToken)).Draft;

    /// <summary>
    /// Every block is fenced as untrusted, including prior agent output.
    /// </summary>
    /// <remarks>
    /// A previous agent's JSON is still model-generated text, so it gets the
    /// same treatment as the concern a person typed.
    /// </remarks>
    internal static string BuildPrompt(DataAnalystOutput analysis, SupportRecommenderContext context, string repairGuidance)
    {
        var allowed = new Dictionary<string, object>
        {
            ["resource_ids"] = context.AllowedResources.Select(r => r.Id).ToList(),
            ["goal_ids"] = context.AllowedGoalIds,
            ["strategy_ids"] = context.AllowedStrategyIds,
            ["citation_ids"] = context.Evidence.Citations.Select(c => c.CitationId).ToList(),
        };
        var evidence = context.Evidence.Citations
            .Select(c => new Dictionary<string, string>
            {
                ["citation_id"] = c.CitationId,
                ["source_type"] = c.SourceType,
                ["source_title"] = c.SourceTitle,
                ["evidence_summary"] = c.EvidenceSummary,
            })
            .ToList();
        string[] blocks =
        [
            PromptBlocks.WrapUntrusted("prior_agent_output_data_analyst", PyJson.Dumps(analysis)),
            PromptBlocks.WrapUntrusted("allowed_ids", PyJson.Dumps(allowed)),
            PromptBlocks.WrapUntrusted("group_evidence", PyJson.Dumps(evidence)),
            PromptBlocks.WrapUntrusted("concern_text", context.ConcernText),
            repairGuidance.Length > 0 ? PromptBlocks.WrapUntrusted("validator_repair_guidance", repairGuidance) : "",
        ];
        return $"Category: {context.Category}. Produce a SupportRecommendationDraft.\n" + string.Join("\n", blocks);
    }

    /// <summary>
    /// Swap the model's citation *ids* for the retriever's citation *objects*.
    /// </summary>
    /// <remarks>
    /// The model chooses which evidence supports its draft, but never authors
    /// the evidence text. An id it invented is dropped, and an empty result
    /// stays empty: attaching every retrieved citation would let an ungrounded
    /// draft pass the validator's citation check.
    /// </remarks>
    internal static DraftResult AttachCitations(SupportRecommendationModelOutput output, SupportRecommenderContext context)
    {
        var byId = new Dictionary<string, Citation>();
        foreach (var c in context.Evidence.Citations)
        {
            byId[c.CitationId] = c;
        }
        // `CitedIds` is not de-duplicated by the contract, so count and attach
        // unique ids only -- otherwise one repeated id inflates both sides of
        // the accounting and duplicates a Citation in the draft.
        var proposed = output.CitedIds.Distinct().ToList();
        var citations = proposed.Where(byId.ContainsKey).Select(id => byId[id]).ToList();

        if (!Contracts.Check(context.DealerGroupId, Contracts.DealerGroupId) || citations.Count > 12 || !citations.All(c => c.IsValid()))
        {
            throw new ModelOutputException("invalid_draft_schema");
        }
        var draft = new SupportRecommendationDraft(
            ContractVersion: output.ContractVersion,
            DealerGroupId: context.DealerGroupId,
            DetectedNeed: output.DetectedNeed,
            SupportTier: output.SupportTier,
            RecommendedFrequency: output.RecommendedFrequency,
            GroupingGuidance: output.GroupingGuidance,
            ResourceIds: output.ResourceIds,
            Rationale: output.Rationale,
            GoalSuggestions: output.GoalSuggestions,
            StrategySuggestions: output.StrategySuggestions,
            ManagerNextSteps: output.ManagerNextSteps,
            ProgressMonitoring: output.ProgressMonitoring,
            ReviewWindowDays: output.ReviewWindowDays,
            DecisionRule: output.DecisionRule,
            Caveats: output.Caveats,
            Citations: citations);
        return new DraftResult(draft, proposed.Count, citations.Count);
    }
}
