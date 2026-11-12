using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using Azure.Monitor.OpenTelemetry.Exporter;
using OpenTelemetry;
using OpenTelemetry.Trace;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Observability comes from Agent Framework instrumentation, not from us.
/// </summary>
/// <remarks>
/// <para>
/// These tests replace a hand-written recorder and its allowlist. Two
/// properties mattered then and still matter now:
/// </para>
/// <para>
/// 1. Every node that runs is observable, or the per-agent latency query in
///    Module 10 silently omits a step.
/// 2. No prompt, concern text or completion ever leaves the process.
/// </para>
/// <para>
/// The second is now enforced by Agent Framework (sensitive-data capture is
/// off by default) rather than by an allowlist we maintain, so the test is a
/// canary against that default changing under us.
/// </para>
/// <para>
/// The listener is installed once for the whole class and captures every
/// span on the app's one <see cref="ActivitySource"/>. Nothing else listens
/// to it in tests, so without the listener the instrumented components
/// produce no spans at all and every assertion here would pass vacuously.
/// </para>
/// </remarks>
public sealed class ObservabilityTests
{
    private const string Canary = "ZZ-CANARY-CONCERN-TEXT";

    // The executors in Workflows/Graph.cs that run on a passing request.
    private static readonly HashSet<string> ExpectedExecutors =
    [
        "retrieve-evidence",
        "data-analyst",
        "support-recommender",
        "validator",
        "finalise",
    ];

    private static readonly List<Activity> Captured = [];

    // Only while a test is capturing: an always-sampling listener left on would
    // record spans the app's own provider would drop, and hide that from
    // Spans_inside_a_request_reach_the_exporter.
    private static volatile bool _capturing;

    private static readonly ActivityListener Listener = Install();

    /// <summary>Listen to Agent Framework's instrumentation, through the app's own source.</summary>
    private static ActivityListener Install()
    {
        var listener = new ActivityListener
        {
            ShouldListenTo = source => source.Name == Observability.SourceName,
            Sample = (ref ActivityCreationOptions<ActivityContext> _) => _capturing ? ActivitySamplingResult.AllDataAndRecorded : ActivitySamplingResult.None,
            ActivityStopped = activity =>
            {
                if (!_capturing)
                {
                    return;
                }
                lock (Captured)
                {
                    Captured.Add(activity);
                }
            },
        };
        ActivitySource.AddActivityListener(listener);
        return listener;
    }

    /// <summary>Run <paramref name="body"/> and return the spans it emitted.</summary>
    private static async Task<List<Activity>> SpansAsync(Func<Task> body)
    {
        GC.KeepAlive(Listener);
        lock (Captured)
        {
            Captured.Clear();
        }
        _capturing = true;
        try
        {
            await body();
        }
        finally
        {
            _capturing = false;
        }
        lock (Captured)
        {
            return [.. Captured];
        }
    }

    private static string Dump(Activity span) => JsonSerializer.Serialize(new
    {
        name = span.DisplayName,
        status = span.StatusDescription ?? "",
        attributes = span.TagObjects.ToDictionary(tag => tag.Key, tag => tag.Value?.ToString()),
        events = span.Events.Select(e => new
        {
            name = e.Name,
            attributes = e.Tags.ToDictionary(tag => tag.Key, tag => tag.Value?.ToString()),
        }),
    });

    [Fact]
    public async Task Every_workflow_node_emits_an_executor_span()
    {
        var (coord, _) = CoordinatorTests.MakeCoord();
        Workflows.CoordinatorResult? result = null;
        var spans = await SpansAsync(async () => result = await coord.RunAsync(CoordinatorTests.Request(), TestContext.Current.CancellationToken));

        Assert.True(result!.AgentTrace.Count > 0, "the run produced no trace to compare against");

        var executorIds = spans
            .Select(span => span.GetTagItem("executor.id")?.ToString())
            .OfType<string>()
            .ToHashSet();
        var missing = ExpectedExecutors.Except(executorIds).Order(StringComparer.Ordinal).ToList();
        Assert.True(missing.Count == 0, $"nodes that ran with no executor span: [{string.Join(", ", missing.Select(m => $"'{m}'"))}]");
    }

    [Fact]
    public async Task Workflow_invocation_is_a_span()
    {
        var (coord, _) = CoordinatorTests.MakeCoord();
        var spans = await SpansAsync(() => coord.RunAsync(CoordinatorTests.Request(), TestContext.Current.CancellationToken));

        var names = spans.Select(span => span.DisplayName).ToHashSet();
        Assert.Contains("invoke_workflow support-plan", names);
        Assert.Contains(names, name => name.StartsWith("executor.process", StringComparison.Ordinal));
    }

    /// <summary>The privacy guarantee, asserted against a canary rather than a list.</summary>
    [Fact]
    public async Task No_user_text_reaches_any_span()
    {
        var (coord, _) = CoordinatorTests.MakeCoord();
        var spans = await SpansAsync(() => coord.RunAsync(CoordinatorTests.Request() with { ConcernText = Canary }, TestContext.Current.CancellationToken));

        // Without this the test passes on an empty list and proves nothing.
        Assert.True(spans.Count > 0, "no spans captured; this assertion would be vacuous");

        foreach (var span in spans)
        {
            Assert.False(Dump(span).Contains(Canary, StringComparison.Ordinal), $"user text leaked into span {span.DisplayName}");
        }
    }

    /// <summary>The failure path leaked where the success path did not.</summary>
    /// <remarks>
    /// Earlier Python releases attached the formatted traceback to the failed
    /// span, whose chained cause was a validation error quoting the offending
    /// value -- model output. The step failure is raised without that cause so
    /// the chain never exists to be recorded.
    ///
    /// Agent Framework for .NET reports a failed node as an executor-failed
    /// event and leaves its span's status unset, where the Python framework
    /// marks the span failed (conformance/allowed_differences.yaml,
    /// failed-step-span-status). So the guard against a vacuous pass here is
    /// that the failing node's own span was captured.
    /// </remarks>
    [Fact]
    public async Task No_model_output_reaches_a_failure_span()
    {
        var bad = Conftest.CannedDataAnalystOutput();
        // Longer than the 500-character cap on `detected_need`, so validation
        // rejects it and could quote what it was given.
        ((Dictionary<string, object?>)bad["analysis"]!)["detected_need"] = Canary + new string('y', 600);

        var (coord, _) = CoordinatorTests.MakeCoord(analystPayload: bad);
        Workflows.CoordinatorResult? result = null;
        var spans = await SpansAsync(async () => result = await coord.RunAsync(CoordinatorTests.Request(), TestContext.Current.CancellationToken));

        Assert.Equal("invalid_model_json", result!.Status);

        var failed = spans.Where(span => span.GetTagItem("executor.id") as string == "data-analyst").ToList();
        Assert.True(failed.Count > 0, "no span recorded the failing node; this assertion would be vacuous");
        foreach (var span in spans)
        {
            Assert.False(Dump(span).Contains(Canary, StringComparison.Ordinal), $"model output leaked into span {span.DisplayName}");
        }
    }

    private sealed class Exported(List<Activity> sink) : BaseProcessor<Activity>
    {
        public override void OnEnd(Activity data)
        {
            lock (sink)
            {
                sink.Add(data);
            }
        }
    }

    /// <summary>The spans of a real request reach the app's own exporter.</summary>
    /// <remarks>
    /// .NET only. ASP.NET Core starts an unsampled activity for every request,
    /// and a sampler that follows the parent drops every Agent Framework span
    /// beneath it: the deployed app exported nothing at all, while the tests
    /// above, which call the coordinator directly, passed. The Azure Monitor
    /// exporter installs such a sampler itself, so this goes through the HTTP
    /// pipeline and the app's own provider setup, with that exporter in it,
    /// and checks the spans are recorded: the exporter sends nothing else.
    /// </remarks>
    [Fact]
    public async Task Spans_inside_a_request_reach_the_exporter()
    {
        var exported = new List<Activity>();
        using var provider = Observability.Tracing(builder => builder
                .AddProcessor(new Exported(exported))
                .AddAzureMonitorTraceExporter(options =>
                {
                    options.ConnectionString = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://ingest.example.invalid/";
                    options.DisableOfflineStorage = true;
                }))
            .Build();
        using var app = Conftest.MakeClient();

        var response = await app.Client.PostAsJsonAsync(
            "/api/recommendations/support-plan",
            new { dealer_group_id = Conftest.DefaultDealerGroup, dealership_id = "DLR-0001", category = "lead-response", concern_text = "First response is slow." },
            TestContext.Current.CancellationToken);
        response.EnsureSuccessStatusCode();

        var recorded = exported.Where(span => span.Recorded).Select(span => span.DisplayName).ToHashSet();
        Assert.Contains("invoke_workflow support-plan", recorded);
        Assert.Contains(recorded, name => name.StartsWith("executor.process", StringComparison.Ordinal));
    }
}
