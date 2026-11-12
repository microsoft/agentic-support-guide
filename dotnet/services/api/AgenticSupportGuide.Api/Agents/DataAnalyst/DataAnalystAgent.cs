using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Agents.DataAnalyst;

public sealed record DataAnalystContext(
    string DealerGroupId,
    string DealershipLabel,
    string RegionId,
    string Segment,
    double ProcessScore,
    double AppointmentAttendanceRate,
    double FollowupIndex,
    double EngagementIndex,
    AreaSeries AreaSeries,
    OperationsSeries OperationsSeries,
    string Category,
    string ConcernText);

/// <summary>The analysis plus the model call that produced it.</summary>
public sealed record AnalysisResult(DataAnalystOutput Output, RoleResponse Call);

/// <summary>
/// Data Analyst Agent - remote Foundry agent invocation.
/// </summary>
/// <remarks>
/// The wrapper attaches <c>dealer_group_id</c> (from context) to the parsed
/// model output. The remote agent itself does not need to know about
/// <c>dealer_group_id</c>; the workflow is the source of truth for tenant
/// boundaries.
/// </remarks>
public sealed class DataAnalystAgent(MafAgentRuntime runtime)
{
    public const string AgentId = "data-analyst";
    public const string AgentName = "data-analyst-agent";

    public async Task<DataAnalystOutput> AnalyzeAsync(DataAnalystContext context, CancellationToken cancellationToken = default) =>
        (await AnalyzeWithCallAsync(context, cancellationToken)).Output;

    public async Task<AnalysisResult> AnalyzeWithCallAsync(DataAnalystContext context, CancellationToken cancellationToken = default)
    {
        // The series, not just their size. Sending only a record count left
        // the model with nothing to compare across areas or over time, which
        // is the whole analysis this agent is asked for.
        var areas = context.AreaSeries;
        var ops = context.OperationsSeries;
        var facts = new Dictionary<string, object?>
        {
            ["dealership_label"] = context.DealershipLabel,
            ["region_id"] = context.RegionId,
            ["segment"] = context.Segment,
            ["process_score"] = context.ProcessScore,
            ["appointment_attendance_rate"] = context.AppointmentAttendanceRate,
            ["followup_index"] = context.FollowupIndex,
            ["engagement_index"] = context.EngagementIndex,
            ["category"] = context.Category,
            ["score_periods"] = areas.Periods,
            ["score_by_process_area"] = areas.ScoresByArea,
            ["latest_band_by_process_area"] = areas.LatestBandByArea,
            ["area_score_count"] = areas.RecordCount,
            ["duplicate_area_records"] = areas.DuplicateCount,
            ["operations_periods"] = ops.Periods,
            ["appointment_attendance_rate_by_period"] = ops.AppointmentAttendanceRate,
            ["escalations_by_period"] = ops.Escalations,
            ["followup_completion_by_period"] = ops.FollowupCompletion,
            ["operations_record_count"] = ops.RecordCount,
        };
        var userPrompt =
            "Analyze the synthetic dealership indicators below and produce the "
            + "structured output required by your instructions.\n"
            + PromptBlocks.WrapUntrusted("synthetic_facts", PyJson.Dumps(facts))
            + "\n"
            + PromptBlocks.WrapUntrusted("concern_text", context.ConcernText);

        var response = await runtime.InvokeAsync(AgentName, userPrompt, typeof(DataAnalystModelOutput), cancellationToken);
        var output = Responses.ParseRoleResponse(response, DataAnalystModelOutput.Parse);
        return new AnalysisResult(
            DataAnalystOutput.Create(output.ContractVersion, context.DealerGroupId, output.Analysis),
            response);
    }
}
