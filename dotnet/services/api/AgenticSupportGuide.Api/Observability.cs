using System.Diagnostics;
using Azure.Monitor.OpenTelemetry.Exporter;
using OpenTelemetry;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace AgenticSupportGuide.Api;

/// <summary>
/// Observability, entirely from Microsoft Agent Framework.
/// </summary>
/// <remarks>
/// There is no recorder and no custom event schema here. The workflow, each
/// agent and each model client are built with Agent Framework's OpenTelemetry
/// instrumentation, all on one <see cref="ActivitySource"/>:
///
/// <code>
///     workflow.build                the graph, with its full definition as JSON
///     invoke_workflow support-plan  one request end to end
///     executor.process &lt;id&gt;         one node, e.g. `executor.process support-recommender`
///     edge_group.process            an edge firing, with its delivery status
///     invoke_agent &lt;agent&gt;          one agent call
///     chat &lt;deployment&gt;             one model call, with gen_ai.* attributes:
///                                   response model, input/output tokens, error type
/// </code>
///
/// Prompt and completion text stays out because sensitive-data capture is off
/// by default. Never turn it on in this app; the workshop runs on a shared
/// subscription and a span is forever.
///
/// https://learn.microsoft.com/agent-framework/agents/observability
/// </remarks>
public static class Observability
{
    /// <summary>The one source every instrumented Agent Framework component reports on.</summary>
    public const string SourceName = "AgenticSupportGuide";

    public static readonly ActivitySource ActivitySource = new(SourceName);

    private static readonly Lock Gate = new();
    private static TracerProvider? _provider;
    private static bool _configured;

    /// <summary>
    /// Export Agent Framework's spans. Returns true when exporting.
    /// </summary>
    /// <remarks>
    /// Idempotent and never fatal: telemetry must not be able to stop the app
    /// from serving.
    ///
    /// Without a connection string this is a no-op. Nothing listens to the
    /// source, so the instrumented components produce no spans at all. That is
    /// the right default for local runs and tests.
    /// </remarks>
    public static bool Configure(string? connectionString)
    {
        lock (Gate)
        {
            if (_configured)
            {
                return !string.IsNullOrEmpty(connectionString);
            }
            _configured = true;
            if (string.IsNullOrEmpty(connectionString))
            {
                return false;
            }
            try
            {
                _provider = Tracing(builder => builder.AddAzureMonitorTraceExporter(options => options.ConnectionString = connectionString))
                    .Build();
                return true;
            }
            catch (Exception)
            {
                // Telemetry must never break a request.
                return false;
            }
        }
    }

    /// <summary>
    /// The tracer provider's setup around an exporter.
    /// </summary>
    /// <remarks>
    /// Every Agent Framework span is recorded, whatever its parent says.
    /// ASP.NET Core starts an activity for each request even though nothing
    /// here exports it, and that activity is never sampled. A sampler that
    /// follows the parent then drops every span beneath it, which in a running
    /// app is all of them: the SDK's default sampler does that, and so does
    /// the one the Azure Monitor exporter installs. So the sampler is set
    /// last, after the exporter has had its say. The Python track's server
    /// starts no request span, so there its workflow spans are roots and the
    /// defaults work.
    /// </remarks>
    public static TracerProviderBuilder Tracing(Action<TracerProviderBuilder> export)
    {
        var builder = Sdk.CreateTracerProviderBuilder()
            .SetResourceBuilder(ResourceBuilder.CreateDefault().AddService(Config.ServiceName, serviceVersion: Config.ServiceVersion))
            .AddSource(SourceName);
        export(builder);
        return builder.SetSampler(new AlwaysOnSampler());
    }
}
