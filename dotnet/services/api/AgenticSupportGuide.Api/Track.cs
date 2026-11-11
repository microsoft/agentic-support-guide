namespace AgenticSupportGuide.Api;

/// <summary>
/// The strings that name this track's own folders and commands.
/// </summary>
/// <remarks>
/// Setup guidance and error messages tell a learner what to run next, and
/// that differs only in the track's paths: the Python track says
/// <c>python/...</c> where this one says <c>dotnet/...</c>. The conformance
/// tests map one onto the other (conformance/allowed_differences.yaml).
/// </remarks>
public static class Track
{
    public const string ValidateAgentDefinitions = "dotnet/scripts/validate_agent_definitions.cs";
    public const string ValidateAgentDefinitionsCommand = "dotnet run dotnet/scripts/validate_agent_definitions.cs";
    public const string PopulateEnv = @".\dotnet\scripts\populate-env.ps1";
    public const string RunBackend = @".\dotnet\scripts\run-backend.ps1";
    public const string EnvFile = "dotnet/services/api/.env";
    public const string InfraDir = "/dotnet/infra";
}
