namespace AgenticSupportGuide.Api;

/// <summary>
/// Identify which build is actually serving.
/// </summary>
/// <remarks>
/// A successful <c>az webapp deploy</c> does not guarantee the new code is
/// live: the previous worker can keep serving. Without a stamp, a stale
/// deployment is indistinguishable from a good one.
///
/// <c>deploy-app.ps1</c> writes <c>build_id.txt</c> next to the app in the
/// zip and then polls <c>/api/health</c> until the served build_id matches
/// what it shipped.
/// </remarks>
public static class BuildInfo
{
    public const string UnknownBuild = "unknown";

    private static readonly string BuildIdFile = Path.Combine(AppContext.BaseDirectory, "build_id.txt");

    /// <summary>Build stamp written at package time, or BUILD_ID, or 'unknown'.</summary>
    public static string CurrentBuildId()
    {
        var envValue = (Environment.GetEnvironmentVariable("BUILD_ID") ?? "").Trim();
        if (envValue.Length > 0)
        {
            return envValue;
        }
        try
        {
            var stamped = File.ReadAllText(BuildIdFile).Trim();
            return stamped.Length > 0 ? stamped : UnknownBuild;
        }
        catch (IOException)
        {
            return UnknownBuild;
        }
        catch (UnauthorizedAccessException)
        {
            return UnknownBuild;
        }
    }
}
