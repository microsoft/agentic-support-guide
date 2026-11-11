using System.Diagnostics;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;
using Microsoft.Agents.AI.Workflows;

namespace AgenticSupportGuide.Api.Workflows;

/// <summary>
/// Entry point to the plan workflow: runs one per request.
/// </summary>
/// <remarks>
/// The orchestration itself is a Microsoft Agent Framework graph -- see
/// <see cref="Graph"/>, which is short enough to read in one sitting. This
/// type starts a run, reads the workflow's own event stream, and hands back its
/// result.
///
/// From that stream it takes three things:
///
/// - the trace rows the working nodes yield as intermediate outputs,
/// - each node's duration, from Agent Framework's executor-invoked and
///   executor-completed / executor-failed events,
/// - the one result <c>Finalise</c> or <c>Refuse</c> yields.
///
/// A node that cannot continue -- no evidence, a provider error, off-contract
/// JSON -- throws <see cref="StepFailedException"/>, and Agent Framework
/// reports it as that executor's failure.
/// </remarks>
public sealed class AgentCoordinator(MafAgentRuntime runtime, IEvidenceRetriever evidenceRetriever, string providerDisplay)
{
    public async Task<CoordinatorResult> RunAsync(CoordinatorRequest request, CancellationToken cancellationToken = default)
    {
        var context = new RunContext(
            CorrelationId: Guid.NewGuid().ToString(),
            DealerGroupId: request.DealerGroupId,
            ProviderModel: providerDisplay);
        var workflow = Graph.BuildPlanWorkflow(request, context, runtime, evidenceRetriever, providerDisplay);

        var concern = PyText.Head(PyText.Strip(request.ConcernText ?? ""), Config.ConcernTextMaxLen);
        var trace = new Trace();
        var outputs = new List<object?>();
        StepFailedException? failure = null;

        await using (var run = await InProcessExecution.RunStreamingAsync(workflow, new PlanState(concern), cancellationToken: cancellationToken))
        {
            await foreach (var evt in run.WatchStreamAsync(cancellationToken))
            {
                trace.Observe(evt);
                switch (evt)
                {
                    case WorkflowOutputEvent output when !output.HasTag(OutputTag.Intermediate):
                        outputs.Add(output.Data);
                        break;
                    case ExecutorFailedEvent failedEvent when StepFailure(failedEvent.Data) is { } failed:
                        failure = failed;
                        break;
                    case WorkflowErrorEvent errorEvent when StepFailure(errorEvent.Exception) is { } failed:
                        failure ??= failed;
                        break;
                    case WorkflowErrorEvent { Exception: { } error }:
                        // Anything else is a defect, not an outcome: surface it.
                        throw new InvalidOperationException("The plan workflow failed.", error);
                }
            }
        }

        if (failure is not null)
        {
            return Results.FailureResult(context, failure.Plan, trace.Steps(), failure.Status, failure.ErrorCode, failure.ErrorMessage);
        }
        return SingleResult(outputs, context, trace.Steps());
    }

    // Agent Framework reports a handler's exception wrapped in the exception
    // that invoked it.
    private static StepFailedException? StepFailure(Exception? error)
    {
        for (var current = error; current is not null; current = current.InnerException)
        {
            if (current is StepFailedException failed)
            {
                return failed;
            }
        }
        return null;
    }

    /// <summary>
    /// Exactly one terminal node may produce a result.
    /// </summary>
    /// <remarks>
    /// Two would mean a conditional edge fired that should not have, which is
    /// the failure mode a shared mutable message causes. <see cref="PlanState"/>
    /// is immutable to prevent it; this is the assertion that it worked.
    /// </remarks>
    private static CoordinatorResult SingleResult(List<object?> outputs, RunContext context, IReadOnlyList<AgentTraceStep> trace)
    {
        var results = outputs.OfType<CoordinatorResult>().ToList();
        if (results.Count == 1)
        {
            return results[0] with { AgentTrace = trace };
        }
        return Results.FailureResult(
            context,
            null,
            trace,
            status: "orchestration_error",
            errorCode: "WORKFLOW_OUTPUT_UNEXPECTED",
            errorMessage: $"Workflow produced {results.Count} results; exactly one was expected.");
    }

    /// <summary>
    /// The trace, read off the workflow's event stream.
    /// </summary>
    /// <remarks>
    /// Each working node yields one <see cref="StepRecord"/> per invocation; its
    /// duration is the time between that node's invoked and completed (or
    /// failed) events.
    /// </remarks>
    private sealed class Trace
    {
        private readonly Dictionary<string, long> _started = [];
        private readonly Dictionary<string, List<StepRecord>> _pending = [];
        private readonly List<AgentTraceStep> _steps = [];

        public void Observe(WorkflowEvent evt)
        {
            switch (evt)
            {
                case ExecutorInvokedEvent invoked:
                    _started[invoked.ExecutorId] = Stopwatch.GetTimestamp();
                    break;
                case WorkflowOutputEvent { Data: StepRecord record } output when output.HasTag(OutputTag.Intermediate):
                    if (!_pending.TryGetValue(output.ExecutorId, out var records))
                    {
                        _pending[output.ExecutorId] = records = [];
                    }
                    records.Add(record);
                    break;
                case ExecutorCompletedEvent completed:
                    Close(completed.ExecutorId);
                    break;
                case ExecutorFailedEvent failed:
                    Close(failed.ExecutorId);
                    break;
            }
        }

        public List<AgentTraceStep> Steps()
        {
            // A run that stopped mid-node never sees that node's closing event.
            foreach (var executorId in _pending.Keys.ToList())
            {
                Close(executorId);
            }
            return [.. _steps];
        }

        private void Close(string executorId)
        {
            var latencyMs = _started.Remove(executorId, out var started)
                ? (int)Stopwatch.GetElapsedTime(started).TotalMilliseconds
                : 0;
            if (!_pending.Remove(executorId, out var records))
            {
                return;
            }
            foreach (var record in records)
            {
                _steps.Add(new AgentTraceStep(
                    Agent: record.Agent,
                    Status: record.Status,
                    Provider: record.Provider,
                    Model: record.Model,
                    LatencyMs: latencyMs,
                    TokenEstimate: record.TokenEstimate,
                    IssueCodes: [.. record.IssueCodes ?? []],
                    WarningCodes: [.. record.WarningCodes ?? []],
                    CitationCount: record.CitationCount));
            }
        }
    }
}
