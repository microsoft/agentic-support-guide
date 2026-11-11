using System.Text.Json;
using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;
using Microsoft.Agents.AI.Workflows;

namespace AgenticSupportGuide.Api.Workflows;

/// <summary>Everything a node needs that is not on the edge.</summary>
public sealed record PlanRun(CoordinatorRequest Request, RunContext Context);

// The six nodes of the plan workflow.
//
// One class per node. Each one is thin: take the PlanState off the edge, do
// one job, report its trace row with YieldOutputAsync, send the next
// PlanState. Graph.cs wires them together.
//
// The four working nodes are the graph's *intermediate* outputs, so their
// trace rows reach the caller on the workflow's own event stream; only
// Finalise and Refuse produce the run's result. Every node gets the same
// PlanRun -- the request and the run's identity. Built fresh per request,
// because a workflow instance refuses concurrent runs.

internal static class Nodes
{
    public const int MaxRepairGuidanceChars = 800;

    public static string ModelOf(RoleResponse? call) =>
        call is not null && call.Model.Length > 0 ? call.Model : Results.LocalStepModel;

    public static int? TokensOf(RoleResponse? call) => call?.TotalTokens;

    /// <summary>
    /// Report the failed row, then hand back the exception that stops the run.
    /// </summary>
    /// <remarks>
    /// The exception carries no inner exception, and that is a privacy
    /// control, not style: Agent Framework records a failing executor's
    /// exception on its spans, and a provider or parse error can carry model
    /// output derived from a dealer group's evidence. The typed code is all
    /// that leaves.
    /// </remarks>
    public static async Task<StepFailedException> FailAsync(
        IWorkflowContext context,
        PlanState plan,
        StepRecord record,
        string status,
        string errorCode,
        string errorMessage,
        CancellationToken cancellationToken)
    {
        await context.YieldOutputAsync(record, cancellationToken);
        return new StepFailedException(status, errorCode, errorMessage, plan);
    }

    /// <summary>Invoke one agent, or report the failure and stop the run.</summary>
    public static async Task<T> CallAgentAsync<T>(
        IWorkflowContext context,
        PlanRun run,
        PlanState plan,
        string agentName,
        Func<Task<T>> invoke,
        CancellationToken cancellationToken)
    {
        try
        {
            return await invoke();
        }
        catch (FoundryProviderException exc)
        {
            var (status, code) = Failures.ClassifyProviderError(exc);
            throw await FailAsync(
                context,
                plan,
                new StepRecord(agentName, status, MafAgentRuntime.ProviderId, run.Context.ProviderModel, IssueCodes: [code]),
                status,
                code,
                Failures.SafeMessage(status),
                cancellationToken);
        }
        catch (Exception exc) when (exc is ArgumentException or JsonException or FormatException)
        {
            // Never put exception text in an issue code. A parse error can
            // quote the offending value, which is model output derived from a
            // dealer group's evidence, and issue codes travel to the response.
            throw await FailAsync(
                context,
                plan,
                new StepRecord(agentName, "invalid_model_json", MafAgentRuntime.ProviderId, run.Context.ProviderModel, IssueCodes: [Failures.InvalidJsonCode(exc)]),
                "invalid_model_json",
                "AGENT_INVALID_JSON",
                "Remote agent returned invalid or off-schema JSON.",
                cancellationToken);
        }
    }

    /// <summary>How many referenced resource ids were in the request's allowed catalog.</summary>
    public static (int Proposed, int Accepted, List<string> Unknown) ResourceAccounting(PlanRun run, PlanState plan)
    {
        var allowed = run.Request.AllowedResources.Select(r => r.Id).ToHashSet();
        var proposed = plan.RequireDraft().ResourceIds.Distinct().ToList();
        var unknown = proposed.Where(id => !allowed.Contains(id)).ToList();
        return (proposed.Count, proposed.Count - unknown.Count, unknown);
    }
}

/// <summary>Grounding, before any model call. An empty bundle stops the run.</summary>
[SendsMessage(typeof(PlanState))]
[YieldsOutput(typeof(StepRecord))]
internal sealed partial class RetrieveEvidence(PlanRun run, IEvidenceRetriever retriever) : Executor<PlanState>("retrieve-evidence")
{
    public override async ValueTask HandleAsync(PlanState message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var plan = message;
        var provider = retriever.ProviderName;
        var model = retriever.ProviderModel;
        var request = run.Request;

        EvidenceBundle bundle;
        try
        {
            bundle = await retriever.RetrieveAsync(
                new EvidenceRequest(
                    DealerGroupId: request.DealerGroupId,
                    Category: request.Category,
                    // The concern is the only natural-language description of the
                    // problem. Without it a semantic retriever searches for the
                    // bare category slug, which matches by luck.
                    DetectedNeedHint: plan.Concern),
                cancellationToken);
        }
        catch (EvidenceRetrievalException exc)
        {
            // The retrieval error stays behind: its safe message is the
            // caller-facing summary, and the original can carry document text.
            throw await Nodes.FailAsync(
                context,
                plan,
                EvidenceFailure(provider, model, $"EVIDENCE_{exc.Code}"),
                "evidence_missing",
                "EVIDENCE_MISSING",
                exc.SafeMessage,
                cancellationToken);
        }

        // An empty bundle is not a successful retrieval. Without this the run
        // spent two model calls and then failed validation as
        // "invalid_model_json", blaming the model for missing evidence.
        if (bundle.IsEmpty())
        {
            throw await Nodes.FailAsync(
                context,
                plan,
                EvidenceFailure(provider, model, "EVIDENCE_EMPTY"),
                "evidence_missing",
                "EVIDENCE_MISSING",
                "No dealer-group-scoped evidence was found for this request.",
                cancellationToken);
        }

        await context.YieldOutputAsync(new StepRecord("evidence-retrieval", "ok", provider, model, CitationCount: bundle.Citations.Count), cancellationToken);
        await context.SendMessageAsync(plan with { Evidence = bundle, EvidenceCount = bundle.Citations.Count }, cancellationToken);
    }

    private static StepRecord EvidenceFailure(string provider, string model, string code) =>
        new("evidence-retrieval", "evidence_missing", provider, model, IssueCodes: [code]);
}

/// <summary>Dealership indicators in, findings out. Outside the repair loop.</summary>
[SendsMessage(typeof(PlanState))]
[YieldsOutput(typeof(StepRecord))]
internal sealed partial class Analyse(PlanRun run, DataAnalystAgent agent) : Executor<PlanState>("data-analyst")
{
    public override async ValueTask HandleAsync(PlanState message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var plan = message;
        var request = run.Request;
        var analystContext = new DataAnalystContext(
            DealerGroupId: request.DealerGroupId,
            DealershipLabel: request.DealershipLabel,
            RegionId: request.RegionId,
            Segment: request.Segment,
            ProcessScore: request.ProcessScore,
            AppointmentAttendanceRate: request.AppointmentAttendanceRate,
            FollowupIndex: request.FollowupIndex,
            EngagementIndex: request.EngagementIndex,
            AreaSeries: request.AreaSeries,
            OperationsSeries: request.OperationsSeries,
            Category: request.Category,
            ConcernText: plan.Concern);
        var result = await Nodes.CallAgentAsync(
            context, run, plan, DataAnalystAgent.AgentName, () => agent.AnalyzeWithCallAsync(analystContext, cancellationToken), cancellationToken);
        await context.YieldOutputAsync(
            new StepRecord(DataAnalystAgent.AgentName, "ok", MafAgentRuntime.ProviderId, Nodes.ModelOf(result.Call), TokenEstimate: Nodes.TokensOf(result.Call)),
            cancellationToken);
        await context.SendMessageAsync(plan with { Analysis = result.Output }, cancellationToken);
    }
}

/// <summary>
/// Findings plus the allowed catalogs in, a draft plan out.
/// </summary>
/// <remarks>
/// The only node the repair edge points back at: a rejected draft is the
/// recommender's problem, so re-running retrieval or analysis would spend a
/// model call and change nothing.
/// </remarks>
[SendsMessage(typeof(PlanState))]
[YieldsOutput(typeof(StepRecord))]
internal sealed partial class Recommend(PlanRun run, SupportRecommendationAgent agent) : Executor<PlanState>("support-recommender")
{
    public override async ValueTask HandleAsync(PlanState message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var plan = message;
        var attempts = plan.Attempts + 1;
        var repairing = attempts > 1;
        // Named so the repair shows as its own row in the trace.
        var agentName = repairing ? $"{SupportRecommendationAgent.AgentName}:repair" : SupportRecommendationAgent.AgentName;
        var guidance = repairing && plan.Report is not null ? Parity.PyText.Head(plan.Report.RepairGuidance, Nodes.MaxRepairGuidanceChars) : "";
        var recommenderContext = new SupportRecommenderContext(
            DealerGroupId: run.Request.DealerGroupId,
            Category: run.Request.Category,
            ConcernText: plan.Concern,
            AllowedResources: run.Request.AllowedResources,
            AllowedGoalIds: run.Request.AllowedGoalIds,
            AllowedStrategyIds: run.Request.AllowedStrategyIds,
            Evidence: plan.RequireEvidence());

        var result = await Nodes.CallAgentAsync(
            context,
            run,
            plan,
            agentName,
            () => agent.RecommendWithCountsAsync(plan.RequireAnalysis(), recommenderContext, guidance, cancellationToken),
            cancellationToken);
        await context.YieldOutputAsync(
            new StepRecord(agentName, "ok", MafAgentRuntime.ProviderId, Nodes.ModelOf(result.Call), TokenEstimate: Nodes.TokensOf(result.Call)),
            cancellationToken);
        // Recorded on every attempt, not only on success: a run that failed
        // validation used to audit zero citations, which read as ungrounded.
        await context.SendMessageAsync(
            plan with
            {
                Draft = result.Draft,
                Attempts = attempts,
                CitationCount = result.Draft.Citations.Count,
                CitationsProposed = result.CitationsProposed,
                CitationsAccepted = result.CitationsAccepted,
            },
            cancellationToken);
    }
}

/// <summary>Deterministic checks decide pass or fail; the model only advises.</summary>
[SendsMessage(typeof(PlanState))]
[YieldsOutput(typeof(StepRecord))]
internal sealed partial class Validate(PlanRun run, ValidatorAgent agent) : Executor<PlanState>("validator")
{
    public override async ValueTask HandleAsync(PlanState message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var plan = message;
        var draft = plan.RequireDraft();
        var request = run.Request;
        var payload = new ValidatorInput(
            plan.RequireAnalysis(),
            draft,
            new ValidatorContext(
                DealerGroupId: request.DealerGroupId,
                AllowedResourceIds: request.AllowedResources.Select(r => r.Id).ToList(),
                AllowedGoalIds: request.AllowedGoalIds,
                AllowedStrategyIds: request.AllowedStrategyIds,
                AllowedCitationIds: plan.RequireEvidence().Citations.Select(c => c.CitationId).ToList(),
                RequiredContractVersion: Contracts.ContractVersion));
        // The advisory critique cannot change a verdict, so the recheck after
        // a repair does not pay for it a second time.
        var useLlmCritique = plan.Attempts == 1;

        var result = await Nodes.CallAgentAsync(
            context, run, plan, ValidatorAgent.AgentName, () => agent.ValidateWithCallAsync(payload, useLlmCritique, cancellationToken), cancellationToken);
        var report = result.Report;
        await context.YieldOutputAsync(
            new StepRecord(
                ValidatorAgent.AgentName,
                report.Passed ? "passed" : "failed",
                MafAgentRuntime.ProviderId,
                Nodes.ModelOf(result.Call),
                TokenEstimate: Nodes.TokensOf(result.Call),
                IssueCodes: report.IssueCodes,
                WarningCodes: report.WarningCodes,
                CitationCount: draft.Citations.Count),
            cancellationToken);
        await context.SendMessageAsync(
            plan with { Report = report, ValidationReached = true, DeterministicChecksTotal = Checks.DeterministicChecks.Count },
            cancellationToken);
    }
}

/// <summary>Terminal node for an accepted draft.</summary>
[YieldsOutput(typeof(CoordinatorResult))]
internal sealed partial class Finalise(PlanRun run, string providerDisplay) : Executor<PlanState>("finalise")
{
    public override async ValueTask HandleAsync(PlanState message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var plan = message;
        var runContext = run.Context;
        var report = plan.RequireReport();
        var (proposed, accepted, unknown) = Nodes.ResourceAccounting(run, plan);
        // The trace is the workflow's event stream, so the coordinator fills it in.
        await context.YieldOutputAsync(
            new CoordinatorResult
            {
                Status = "ok",
                ErrorCode = null,
                ErrorMessage = null,
                Recommendation = Assembly.BuildRecommendation(plan.RequireAnalysis(), plan.RequireDraft(), run.Request.AllowedResources, report, providerDisplay),
                AgentTrace = [],
                ProviderModel = runContext.ProviderModel,
                CorrelationId = runContext.CorrelationId,
                DealerGroupId = run.Request.DealerGroupId,
                EvidenceCount = plan.EvidenceCount,
                CitationCount = plan.CitationCount,
                ValidatorStatus = report.SafeSummary.Length > 0 ? report.SafeSummary : "passed",
                CitationsProposed = plan.CitationsProposed,
                CitationsAccepted = plan.CitationsAccepted,
                ResourcesProposed = proposed,
                ResourcesAccepted = accepted,
                UnknownResourceIds = unknown,
                Attempts = plan.Attempts == 0 ? null : plan.Attempts,
                ValidationReached = plan.ValidationReached,
                DeterministicChecksTotal = plan.DeterministicChecksTotal,
            },
            cancellationToken);
    }
}

/// <summary>Terminal node for a draft rejected twice. Returns no recommendation.</summary>
[YieldsOutput(typeof(CoordinatorResult))]
internal sealed partial class Refuse(PlanRun run) : Executor<PlanState>("refuse")
{
    public override async ValueTask HandleAsync(PlanState message, IWorkflowContext context, CancellationToken cancellationToken = default)
    {
        var plan = message;
        var report = plan.RequireReport();
        var (proposed, accepted, unknown) = Nodes.ResourceAccounting(run, plan);
        var result = Results.FailureResult(
            run.Context,
            plan,
            [],
            status: "validation_failed",
            errorCode: "VALIDATION_FAILED_AFTER_REPAIR",
            errorMessage: "Recommendation could not be validated after one repair attempt. No recommendation is returned.",
            validatorStatus: report.SafeSummary.Length > 0 ? report.SafeSummary : "failed");
        // A refusal is the one outcome where an out-of-catalog resource id is
        // still visible: on the accepted path the validator has already
        // rejected any draft that carried one.
        await context.YieldOutputAsync(
            result with { ResourcesProposed = proposed, ResourcesAccepted = accepted, UnknownResourceIds = unknown },
            cancellationToken);
    }
}
