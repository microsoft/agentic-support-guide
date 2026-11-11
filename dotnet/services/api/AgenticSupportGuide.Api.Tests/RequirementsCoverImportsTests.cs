using System.Reflection;
using System.Text.Json;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Guard against shipping a reference the published app does not carry.
/// </summary>
/// <remarks>
/// <para>
/// In the Python track, <c>azure-search-documents</c> was importable locally
/// but missing from requirements.txt, so the deployed app returned 500 on
/// every grounded request while /api/health still reported ok.
/// </para>
/// <para>
/// The compiler rules out the plain version of that here: code cannot use a
/// package the project does not reference. The .NET form of the failure is a
/// reference that compiles but is not published - a package referenced with
/// its runtime assets excluded, for example - which works on a machine that
/// happens to have the assembly and fails on App Service the first time it
/// loads. <c>dotnet publish</c> copies exactly what the app's
/// <c>.deps.json</c> lists, so every assembly the API references must be
/// either listed there or part of the shared framework App Service provides.
/// </para>
/// </remarks>
public sealed class RequirementsCoverImportsTests
{
    private const string DepsFile = "AgenticSupportGuide.Api.deps.json";

    /// <summary>Every runtime assembly the publish manifest lists, by name, with the library that ships it.</summary>
    private static Dictionary<string, string> Shipped()
    {
        using var deps = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, DepsFile)));
        var target = deps.RootElement.GetProperty("runtimeTarget").GetProperty("name").GetString()!;
        var shipped = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var library in deps.RootElement.GetProperty("targets").GetProperty(target).EnumerateObject())
        {
            if (library.Value.TryGetProperty("runtime", out var runtime))
            {
                foreach (var file in runtime.EnumerateObject())
                {
                    shipped[Path.GetFileNameWithoutExtension(file.Name)] = library.Name;
                }
            }
        }
        return shipped;
    }

    /// <summary>The shared frameworks the App Service runtime provides.</summary>
    private static HashSet<string> FrameworkDirectories() =>
    [
        Path.GetDirectoryName(typeof(object).Assembly.Location)!,
        Path.GetDirectoryName(typeof(Microsoft.AspNetCore.Builder.WebApplication).Assembly.Location)!,
    ];

    [Fact]
    public void Every_third_party_import_is_declared()
    {
        var shipped = Shipped();
        var framework = FrameworkDirectories();

        var missing = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var reference in typeof(Program).Assembly.GetReferencedAssemblies())
        {
            if (shipped.ContainsKey(reference.Name!))
            {
                continue;
            }
            var location = Assembly.Load(reference).Location;
            if (framework.Contains(Path.GetDirectoryName(location)!))
            {
                continue;
            }
            missing[reference.Name!] = location;
        }

        var detail = string.Join(", ", missing.Select(item => $"{item.Key} -> {item.Value}"));
        Assert.True(
            missing.Count == 0,
            $"references whose assembly is not in {DepsFile}: {detail}. The deployed app will fail when it first loads them.");
    }
}
