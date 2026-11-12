using System.Net.Http.Headers;
using System.Text.Json;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api;

/// <summary>
/// The HTTP conventions the API keeps: JSON bodies, <c>{"detail": ...}</c>
/// errors, and the 422 shape the web app reads.
/// </summary>
public static class Http
{
    /// <summary>Exactly what the web app and the Python track send, no charset parameter.</summary>
    public const string JsonContentType = "application/json";

    public static IResult Json(object? value, int status = 200, params (string Name, string Value)[] headers) =>
        new JsonBodyResult(value, status, headers);

    /// <summary>An error the caller can act on, as <c>{"detail": "..."}</c>.</summary>
    public static IResult Detail(int status, string detail, params (string Name, string Value)[] headers) =>
        Json(new Dictionary<string, string> { ["detail"] = detail }, status, headers);

    /// <summary>
    /// A request that did not match the expected shape.
    /// </summary>
    /// <remarks>
    /// The default ASP.NET Core and FastAPI bodies echo the rejected value
    /// back, which puts submitted concern text into an HTTP response and any
    /// log that records it. Report where the request was wrong, never what was
    /// in it.
    /// </remarks>
    public static IResult ValidationFailed(IEnumerable<string> fields) =>
        Json(
            new Dictionary<string, object>
            {
                ["status"] = "invalid_request",
                ["error_code"] = "REQUEST_VALIDATION_FAILED",
                ["error_message"] = "The request body did not match the expected shape.",
                ["fields"] = fields.Distinct().Order(StringComparer.Ordinal).ToList(),
            },
            422);

    private sealed class JsonBodyResult(object? value, int status, (string Name, string Value)[] headers) : IResult
    {
        public async Task ExecuteAsync(HttpContext httpContext)
        {
            var response = httpContext.Response;
            response.StatusCode = status;
            foreach (var (name, headerValue) in headers)
            {
                response.Headers[name] = headerValue;
            }
            response.ContentType = JsonContentType;
            if (HttpMethods.IsHead(httpContext.Request.Method))
            {
                return;
            }
            await JsonSerializer.SerializeAsync(response.Body, value, value?.GetType() ?? typeof(object), PyJson.SerializerOptions, httpContext.RequestAborted);
        }
    }
}

/// <summary>
/// A request body, read the way FastAPI reads one.
/// </summary>
/// <remarks>
/// The order is part of the API's behaviour: a body that is not valid JSON is
/// rejected before the key is checked, and the key is checked before the body
/// is validated. A route opts in with <see cref="Marker"/>.
/// </remarks>
public sealed class JsonBody
{
    public static readonly JsonBodyMarker Marker = new();

    private const string ItemKey = "asg.json-body";

    private JsonBody(BodyKind kind, JsonElement value = default)
    {
        Kind = kind;
        Value = value;
    }

    public enum BodyKind
    {
        /// <summary>No bytes at all.</summary>
        Missing,

        /// <summary>Bytes with a content type that is not JSON.</summary>
        NotJson,

        /// <summary>A JSON content type, but not JSON.</summary>
        Unparseable,

        /// <summary>Parsed JSON.</summary>
        Parsed,
    }

    public BodyKind Kind { get; }

    public JsonElement Value { get; }

    public static JsonBody Of(HttpContext context) =>
        context.Items.TryGetValue(ItemKey, out var body) && body is JsonBody read ? read : new JsonBody(BodyKind.Missing);

    public static async Task<JsonBody> ReadAsync(HttpContext context)
    {
        using var buffer = new MemoryStream();
        await context.Request.Body.CopyToAsync(buffer, context.RequestAborted);
        var bytes = buffer.ToArray();
        JsonBody body;
        if (bytes.Length == 0)
        {
            body = new JsonBody(BodyKind.Missing);
        }
        else if (!IsJsonContentType(context.Request.ContentType))
        {
            body = new JsonBody(BodyKind.NotJson);
        }
        else
        {
            body = Parse(bytes);
        }
        context.Items[ItemKey] = body;
        return body;
    }

    private static JsonBody Parse(byte[] bytes)
    {
        var span = bytes.AsMemory();
        if (span.Span.StartsWith((ReadOnlySpan<byte>)[0xEF, 0xBB, 0xBF]))
        {
            span = span[3..];
        }
        try
        {
            using var document = JsonDocument.Parse(span);
            return new JsonBody(BodyKind.Parsed, document.RootElement.Clone());
        }
        catch (JsonException)
        {
            return new JsonBody(BodyKind.Unparseable);
        }
    }

    // No content type is read as JSON; so is application/json and any +json.
    private static bool IsJsonContentType(string? contentType)
    {
        if (string.IsNullOrEmpty(contentType))
        {
            return true;
        }
        if (!MediaTypeHeaderValue.TryParse(contentType, out var parsed) || parsed.MediaType is null)
        {
            return false;
        }
        var parts = parsed.MediaType.ToLowerInvariant().Split('/');
        return parts.Length == 2 && parts[0] == "application" && (parts[1] == "json" || parts[1].EndsWith("+json", StringComparison.Ordinal));
    }

    /// <summary>Endpoint metadata: this route reads a JSON body.</summary>
    public sealed class JsonBodyMarker;
}

/// <summary>
/// Every route except <c>/api/health</c> requires the key. <c>/api/health</c>
/// is the only anonymous route: deploy-app.ps1 and CI poll it to find out
/// which build is serving, and that runs before the web tier is up.
/// </summary>
public sealed class ApiKeyFilter : IEndpointFilter
{
    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next)
    {
        var http = context.HttpContext;
        if (http.GetEndpoint()?.Metadata.GetMetadata<JsonBody.JsonBodyMarker>() is not null)
        {
            var body = await JsonBody.ReadAsync(http);
            if (body.Kind == JsonBody.BodyKind.Unparseable)
            {
                return Http.ValidationFailed(["body"]);
            }
        }
        return Auth.RequireApiKey(http.Request) ?? await next(context);
    }
}
