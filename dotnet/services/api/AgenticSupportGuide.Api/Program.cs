using System.Text.Json;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.Parity;

// Application wiring. The routes live in Endpoints.cs, and the agent workflow
// in Workflows/.

var builder = WebApplication.CreateBuilder(args);

builder.Services.ConfigureHttpJsonOptions(options => PyJson.Configure(options.SerializerOptions));
builder.Services.AddSingleton(sp => AppServicesFactory.Build(sp.GetService<AppOverrides>(), sp.GetRequiredService<ILoggerFactory>()));

// Explicit allowlist rather than relying on the Vite dev proxy: if this app is
// ever served directly, no CORS policy means any origin can call it.
// Credentials are deliberately not allowed.
builder.Services.AddCors(options => options.AddDefaultPolicy(policy => policy
    .WithOrigins(AllowedOrigins())
    .WithMethods("GET", "POST", "OPTIONS")
    .WithHeaders("Content-Type")));

// The generated OpenAPI document and Swagger UI would hand the full schema to
// anyone who asked on App Service, outside the key check. Local development
// keeps them: the API is on a laptop and /api/docs is how learners explore it.
var exploreApi = !Auth.RunningOnAppService();
if (exploreApi)
{
    builder.Services.AddOpenApi(options => options.AddDocumentTransformer((document, _, _) =>
    {
        document.Info.Title = "Agentic Support Guide API";
        document.Info.Version = Config.ServiceVersion;
        document.Info.Description =
            "Prototype API demonstrating three collaborating agents. The coordinator composes each role in-process "
            + "with Microsoft Agent Framework and calls Microsoft Foundry models; the same definitions are also "
            + "published to Foundry as prompt agents. Synthetic data only.";
        return Task.CompletedTask;
    }));
}

var app = builder.Build();

// Built now rather than on the first request, as the Python track builds its
// services when the app is created.
app.Services.GetRequiredService<AppServices>();

// An unmatched route or method answers with {"detail": ...}, the same body
// the error responses use.
app.UseStatusCodePages(async context =>
{
    var response = context.HttpContext.Response;
    var detail = response.StatusCode switch
    {
        404 => "Not Found",
        405 => "Method Not Allowed",
        _ => null,
    };
    if (detail is null)
    {
        return;
    }
    response.ContentType = Http.JsonContentType;
    if (!HttpMethods.IsHead(context.HttpContext.Request.Method))
    {
        await JsonSerializer.SerializeAsync(response.Body, new Dictionary<string, string> { ["detail"] = detail }, PyJson.SerializerOptions);
    }
});

app.UseRouting();
app.UseCors();

// A trailing slash on a known route redirects to the route, rather than
// matching it silently.
app.Use(async (context, next) =>
{
    var path = context.Request.Path.Value ?? "";
    if (path.Length > 1 && path.EndsWith('/') && context.GetEndpoint() is not null)
    {
        var request = context.Request;
        context.Response.StatusCode = StatusCodes.Status307TemporaryRedirect;
        context.Response.Headers.Location = $"{request.Scheme}://{request.Host}{request.PathBase}{path.TrimEnd('/')}{request.QueryString}";
        return;
    }
    await next(context);
});

if (exploreApi)
{
    app.MapOpenApi("/api/openapi.json");
    app.UseSwaggerUI(options =>
    {
        options.RoutePrefix = "api/docs";
        options.SwaggerEndpoint("/api/openapi.json", "Agentic Support Guide API");
    });
}

Endpoints.Map(app);

app.Run();

// Vite dev server. Override with a comma-separated ALLOWED_ORIGINS when the API
// is served anywhere other than the local dev proxy.
static string[] AllowedOrigins()
{
    var configured = (Environment.GetEnvironmentVariable("ALLOWED_ORIGINS") ?? "")
        .Split(',')
        .Select(o => o.Trim())
        .Where(o => o.Length > 0)
        .ToArray();
    return configured.Length > 0 ? configured : ["http://127.0.0.1:5173", "http://localhost:5173"];
}

/// <summary>The entry point, visible to the tests' WebApplicationFactory.</summary>
public partial class Program;
