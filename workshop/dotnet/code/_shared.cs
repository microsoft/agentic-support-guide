// Shared setup for the workshop samples.
//
// Every sample needs the same two settings and the same project client, so
// that lives here rather than being re-typed seven times. A sample pulls it
// in with `#:include _shared.cs`.
//
// The names are read in two forms. `FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_MODEL`
// are what the Agent Framework docs use, so a sample copied out of this repo
// matches what you read there. `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` /
// `FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER` are what Module 0's `populate-env.ps1`
// writes, so if you have already done Module 0 the samples just work.

#:package Microsoft.Agents.AI.Foundry
#:package Azure.Identity

using System.Runtime.CompilerServices;
using Azure.AI.Projects;
using Azure.Identity;

public static class Workshop
{
    // (docs name, this repo's name)
    public static readonly string[] EndpointVars = ["FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"];
    public static readonly string[] ModelVars = ["FOUNDRY_MODEL", "FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER"];

    private static readonly string EnvFile = Path.GetFullPath(Path.Combine(ThisDir(), "..", "..", "..", "dotnet", "services", "api", ".env"));

    /// <summary>Read dotnet/services/api/.env if Module 0 created it. Never overrides a real env var.</summary>
    private static void LoadEnvFile()
    {
        if (!File.Exists(EnvFile))
        {
            return;
        }
        foreach (var raw in File.ReadAllLines(EnvFile))
        {
            var line = raw.Trim();
            if (line.Length > 0 && !line.StartsWith('#') && line.Contains('='))
            {
                var at = line.IndexOf('=');
                var key = line[..at].Trim();
                if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(key)))
                {
                    Environment.SetEnvironmentVariable(key, line[(at + 1)..].Trim());
                }
            }
        }
    }

    /// <summary>First of <paramref name="names"/> that is set, or a message naming both and exiting.</summary>
    public static string Setting(string[] names, string example)
    {
        LoadEnvFile();
        foreach (var name in names)
        {
            var value = (Environment.GetEnvironmentVariable(name) ?? "").Trim();
            if (value.Length > 0)
            {
                return value;
            }
        }
        var (docsName, repoName) = (names[0], names[1]);
        Console.Error.WriteLine(
            $"Set {docsName} (or run Module 0, which writes {repoName}).\n\n"
            + $"  $env:{docsName} = \"{example}\"\n"
            + "  az login\n");
        Environment.Exit(2);
        return "";
    }

    /// <summary>A Foundry project client authenticated with your <c>az login</c> session.</summary>
    /// <remarks>
    /// <see cref="AzureCliCredential"/> rather than <see cref="DefaultAzureCredential"/>
    /// so a sample fails immediately with "run az login" instead of spending 30
    /// seconds probing credential sources that are not configured on a laptop.
    /// The deployed app uses <see cref="DefaultAzureCredential"/>, because there
    /// the identity is a managed identity rather than your CLI session.
    /// </remarks>
    public static AIProjectClient Project() => new(
        new Uri(Setting(EndpointVars, "https://<your-project>.services.ai.azure.com/api/projects/<name>")),
        new AzureCliCredential());

    /// <summary>The model deployment the samples' agents run on.</summary>
    public static string Model() => Setting(ModelVars, "gpt-4.1-mini");

    public static void Banner(string title) => Console.WriteLine($"\n=== {title} ===");

    private static string ThisDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;
}
