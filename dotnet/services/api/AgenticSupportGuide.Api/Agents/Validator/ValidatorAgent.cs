using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Agents.Validator;

/// <summary>The verdict plus the advisory model call, if one was made and answered.</summary>
public sealed record ValidationResult(ValidatorReport Report, RoleResponse? Call);

/// <summary>
/// Validator Agent.
/// </summary>
/// <remarks>
/// Deterministic checks decide pass/fail; they live in <see cref="Checks"/>.
/// The optional remote LLM critique may only add advisory warning codes.
/// Repair guidance comes from the fixed templates in <see cref="Repair"/>. Raw
/// model critique never reaches the UI or the audit trail.
///
/// What is checked, in this iteration:
///
/// - contract-version match,
/// - allowed resource / goal / strategy IDs,
/// - required caveats (including "human review"),
/// - required support-tier framing,
/// - required progress-monitoring and next steps,
/// - rationale is non-empty,
/// - **at least one citation** on the draft,
/// - **every citation.dealer_group_id matches the request dealer_group_id**,
/// - **every citation_id is in the allowed set** produced by the retriever,
/// - no pricing/credit/compliance/safety/staffing determinations, in **any** draft field.
/// </remarks>
public sealed class ValidatorAgent(MafAgentRuntime runtime)
{
    public const string AgentId = "validator";
    public const string AgentName = "validator-agent";

    public const int MaxLlmWarnings = 10;

    public async Task<ValidatorReport> ValidateAsync(ValidatorInput payload, bool useLlmCritique, CancellationToken cancellationToken = default) =>
        (await ValidateWithCallAsync(payload, useLlmCritique, cancellationToken)).Report;

    public async Task<ValidationResult> ValidateWithCallAsync(ValidatorInput payload, bool useLlmCritique, CancellationToken cancellationToken = default)
    {
        var findings = Checks.RunChecks(payload);
        var issueCodes = findings.IssueCodes.Distinct().Order(StringComparer.Ordinal).ToList();
        var (warningCodes, call) = useLlmCritique ? await AdvisoryWarningsAsync(payload, cancellationToken) : ([], null);

        return new ValidationResult(
            ValidatorReport.Create(
                dealerGroupId: payload.Context.DealerGroupId,
                passed: findings.Passed,
                issueCodes: issueCodes,
                warningCodes: warningCodes.Distinct().Order(StringComparer.Ordinal).ToList(),
                failedFields: findings.FailedFields.Distinct().Order(StringComparer.Ordinal).ToList(),
                safeSummary: Repair.SafeSummary(findings.Passed, issueCodes),
                repairGuidance: Repair.BuildRepairGuidance(findings.IssueCodes, findings.UnknownResourceIds)),
            call);
    }

    /// <summary>
    /// Critique is a nice-to-have, so no failure here changes the verdict.
    /// </summary>
    /// <remarks>
    /// The two failure modes are reported separately: a call that never landed
    /// is an environment problem, while a call that returned unparseable JSON
    /// points at the agent definition or the model.
    /// </remarks>
    private async Task<(List<string> Codes, RoleResponse? Call)> AdvisoryWarningsAsync(ValidatorInput payload, CancellationToken cancellationToken)
    {
        if (!runtime.HasRole(AgentName))
        {
            return ([], null);
        }
        RoleResponse? response = null;
        try
        {
            response = await runtime.InvokeAsync(AgentName, CritiquePrompt(payload), typeof(ValidatorCritiqueModelOutput), cancellationToken);
            return (WarningCodes(response), response);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            // Advisory only: a provider error or anything else is reported, never raised.
            return (["VALIDATOR_LLM_CRITIQUE_UNAVAILABLE"], response);
        }
    }

    private static string CritiquePrompt(ValidatorInput payload)
    {
        var analystBlock = PromptBlocks.WrapUntrusted("prior_agent_output_data_analyst", PyJson.Dumps(payload.Analysis));
        var draftBlock = PromptBlocks.WrapUntrusted("prior_agent_output_support_recommender", PyJson.Dumps(payload.Draft));
        return "Critique the draft against the analyst evidence. Return only "
            + "JSON: {warning_codes:string[], repair_guidance:string}. "
            + "Warning codes must be uppercase snake case. Repair guidance "
            + "must be under 500 characters.\n"
            + $"{analystBlock}\n{draftBlock}";
    }

    /// <summary>
    /// Returns warning codes only.
    /// </summary>
    /// <remarks>
    /// The model's own repair text is deliberately discarded: repair guidance
    /// shown to a person has to come from <see cref="Repair"/>.
    /// </remarks>
    private static List<string> WarningCodes(RoleResponse response)
    {
        ValidatorCritiqueModelOutput critique;
        try
        {
            critique = Responses.ParseRoleResponse(response, ValidatorCritiqueModelOutput.Parse);
        }
        catch (ModelOutputException)
        {
            // Not silence: an off-schema critique means the agent definition
            // or the model drifted, and that is worth seeing in the trace.
            return ["VALIDATOR_LLM_CRITIQUE_UNPARSEABLE"];
        }
        return critique.WarningCodes
            .Select(PromptBlocks.EnforceCode)
            .Where(code => code is not null)
            .Select(code => code!)
            .Take(MaxLlmWarnings)
            .ToList();
    }
}
