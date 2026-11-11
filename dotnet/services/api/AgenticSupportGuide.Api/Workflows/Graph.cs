using AgenticSupportGuide.Api.Agents.DataAnalyst;
using AgenticSupportGuide.Api.Agents.SupportRecommender;
using AgenticSupportGuide.Api.Agents.Validator;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;
using Microsoft.Agents.AI.Workflows;

namespace AgenticSupportGuide.Api.Workflows;

/// <summary>
/// The workflow, as a Microsoft Agent Framework graph.
/// </summary>
/// <remarks>
/// This is the whole orchestration. Six nodes and six edges:
///
/// <code>
///     retrieve-evidence -> data-analyst -> support-recommender -> validator
///                                  ^                                 |
///                                  +--------- one repair ------------+
///                                                                    |
///                                              passed -> finalise    |
///                                            exhausted -> refuse  <--+
/// </code>
///
/// Sequential orchestration with one conditional repair edge. The order is
/// fixed; no agent chooses who runs next. The only branch is the validator's
/// verdict, decided by the deterministic checks in
/// <c>Agents/Validator/Checks.cs</c>.
///
/// <c>WorkflowVisualizer.ToMermaidString(...)</c> draws it, and
/// <c>dotnet/scripts/render_workflow_diagram.cs</c> puts that picture in the
/// workshop.
///
/// https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
/// </remarks>
public static class Graph
{
    /// <summary>
    /// Build one workflow for one request.
    /// </summary>
    /// <remarks>
    /// Never cached. A workflow instance rejects concurrent runs, and these
    /// nodes hold this request's identity, so two callers must not share one.
    /// </remarks>
    public static Workflow BuildPlanWorkflow(
        CoordinatorRequest request,
        RunContext context,
        MafAgentRuntime runtime,
        IEvidenceRetriever evidenceRetriever,
        string providerDisplay)
    {
        var run = new PlanRun(request, context);

        var retrieve = new RetrieveEvidence(run, evidenceRetriever);
        var analyse = new Analyse(run, new DataAnalystAgent(runtime));
        var recommend = new Recommend(run, new SupportRecommendationAgent(runtime));
        var validate = new Validate(run, new ValidatorAgent(runtime));
        var finalise = new Finalise(run, providerDisplay);
        var refuse = new Refuse(run);

        return new WorkflowBuilder(retrieve)
            .WithName("support-plan")
            .WithDescription("Sequential orchestration with one conditional repair edge.")
            // Only these two produce the run's result. Naming them keeps a
            // future yield from joining it.
            .WithOutputFrom(finalise, refuse)
            // The working nodes yield their trace rows; these arrive on the
            // event stream as intermediate outputs, never as the result.
            .WithOutputFrom([retrieve, analyse, recommend, validate], OutputTag.Intermediate)
            .AddEdge(retrieve, analyse)
            .AddEdge(analyse, recommend)
            .AddEdge(recommend, validate)
            .AddEdge<PlanState>(validate, finalise, condition: Plan.Passed)
            .AddEdge<PlanState>(validate, recommend, condition: Plan.NeedsRepair)
            .AddEdge<PlanState>(validate, refuse, condition: Plan.RepairExhausted)
            .WithOpenTelemetry(activitySource: Observability.ActivitySource)
            .Build();
    }
}
