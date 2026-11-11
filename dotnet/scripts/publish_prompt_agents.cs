#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Publish the three roles to Foundry as **prompt agents**.
//
// GenAIOps step, deliberately separate from Terraform (DevOps). Terraform
// provisions infrastructure; this publishes agent definitions. Neither one
// does the other's job.
//
// Why prompt agents: they are Foundry's current agent model, so they render
// natively in the portal Agents list. The definition published here is
// composed from the same `/agents/<id>/agent.md` the runtime uses, so what you
// see in the portal is what the app runs.
//
// Usage:
//   dotnet run dotnet/scripts/publish_prompt_agents.cs                  # dry run
//   dotnet run dotnet/scripts/publish_prompt_agents.cs -- --apply       # publish a version
//   dotnet run dotnet/scripts/publish_prompt_agents.cs -- --list        # what's in the project

using System.CommandLine;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;
using Azure.AI.Projects;
using Azure.AI.Projects.Agents;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Foundry;
using Microsoft.Extensions.AI;

// The tests compile this file too, and call its methods directly.
#if !UNDER_TEST
return await PublishPromptAgents.MainAsync(args);
#endif

public static partial class PublishPromptAgents
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string EnvFile = Path.Combine(TrackRoot, "services", "api", ".env");
    private const string AgentNamePrefix = "asg-";
    private const int PublishAttempts = 3;
    private const int PublishBackoffSeconds = 10;

    /// <summary>Learner-suffixed so a whole workshop can share one Foundry project.</summary>
    /// <remarks>
    /// <paramref name="variant"/> gives Module 8 a second independently
    /// addressable agent alongside the base name. Publishing twice under the
    /// same name would only add versions, and the newest would win - there
    /// would be nothing to compare.
    /// </remarks>
    public static string AgentName(string role, string suffix, string variant = "")
    {
        var tail = variant.Length > 0 ? $"-{variant}" : "";
        return $"{AgentNamePrefix}{role}-{suffix}{tail}";
    }

    /// <summary>The exact names a delete may touch.</summary>
    /// <remarks>
    /// Names are <c>&lt;prefix&gt;&lt;role&gt;-&lt;suffix&gt;[-&lt;variant&gt;]</c>,
    /// all single-dash, so <c>asg-explainer-ann-smith</c> is genuinely
    /// ambiguous: it could be suffix <c>ann</c> + variant <c>smith</c>, or
    /// suffix <c>ann-smith</c> with no variant. No prefix match can resolve
    /// that, and a <c>StartsWith(base + "-")</c> meant learner <c>ann</c>
    /// deleted learner <c>ann-smith</c>'s agents.
    ///
    /// So: exact names only. Variants must be named explicitly with
    /// <c>--variant</c>, which is how they were created in the first place.
    /// Scoped to the named variant only: seeding the base names too would make
    /// <c>--variant strict --delete</c> wipe every agent for the suffix, which
    /// is the opposite of naming one explicitly.
    /// </remarks>
    public static HashSet<string> DeleteTargets(string suffix, IReadOnlyCollection<string> variants)
    {
        var roles = RoleDefinitions.AllAgentDirs.Values;
        if (variants.Count > 0)
        {
            return [.. variants.SelectMany(variant => roles.Select(role => AgentName(role, suffix, variant)))];
        }
        return [.. roles.Select(role => AgentName(role, suffix))];
    }

    public static async Task<int> MainAsync(string[] args)
    {
        // Must precede parsing: the --suffix default reads the environment.
        LoadEnv();

        var apply = new Option<bool>("--apply") { Description = "Publish a new version of each agent." };
        var list = new Option<bool>("--list") { Description = "List agents in the project and exit." };
        var delete = new Option<bool>("--delete") { Description = "Delete this learner's agents. Requires --suffix." };
        var suffixOption = new Option<string>("--suffix")
        {
            Description = "Learner suffix appended to every agent name, so learners sharing a "
                + "project never collide. Defaults to WORKSHOP_LEARNER_SUFFIX.",
            DefaultValueFactory = _ => Environment.GetEnvironmentVariable("WORKSHOP_LEARNER_SUFFIX") ?? "",
        };
        var workshopOnly = new Option<bool>("--workshop-only") { Description = "Publish only the standalone workshop agents, not the coordinator roles." };
        var rolesOnly = new Option<bool>("--roles-only") { Description = "Publish only the coordinator roles, leaving the explainer untouched." };
        var variantOption = new Option<string>("--variant")
        {
            Description = "Extra name segment, e.g. --variant baseline. Publishes the same "
                + "definition under a second name, for the Module 8 comparison.",
            DefaultValueFactory = _ => "",
        };
        var command = new RootCommand("Publish the three roles to Foundry as prompt agents.")
        {
            apply, list, delete, suffixOption, workshopOnly, rolesOnly, variantOption,
        };
        command.Validators.Add(result =>
        {
            if (result.GetValue(workshopOnly) && result.GetValue(rolesOnly))
            {
                result.AddError("argument --roles-only: not allowed with argument --workshop-only");
            }
        });
        command.SetAction(async (parsed, _) =>
        {
            if (parsed.GetValue(list))
            {
                return RequireEndpoint() is { } listEndpoint ? await ListAgentsAsync(listEndpoint) : 2;
            }

            // Argument validation first: a bad --suffix is the caller's to fix,
            // and reporting a missing endpoint instead would send them down the
            // wrong path.
            var suffix = PyText.Lower(PyText.Strip(parsed.GetValue(suffixOption) ?? ""));
            if (suffix.Length == 0)
            {
                Console.Error.WriteLine(
                    "A learner suffix is required so agents do not collide in a shared "
                    + "Foundry project. Pass --suffix <your-alias> or set WORKSHOP_LEARNER_SUFFIX.");
                return 2;
            }
            if (!SuffixRe().IsMatch(suffix))
            {
                Console.Error.WriteLine($"Invalid suffix {PyText.Repr(suffix)}. Use 1-24 chars of a-z, 0-9 or '-'.");
                return 2;
            }

            var variant = PyText.Lower(PyText.Strip(parsed.GetValue(variantOption) ?? ""));
            if (variant.Length > 0 && !VariantRe().IsMatch(variant))
            {
                Console.Error.WriteLine($"Invalid variant {PyText.Repr(variant)}. Use 1-16 chars of a-z, 0-9 or '-'.");
                return 2;
            }

            if (RequireEndpoint() is not { } endpoint)
            {
                return 2;
            }

            if (parsed.GetValue(delete))
            {
                return await DeleteAgentsAsync(endpoint, suffix, variant.Length > 0 ? [variant] : []);
            }

            var dirs = parsed.GetValue(workshopOnly) ? RoleDefinitions.WorkshopAgentDirs
                : parsed.GetValue(rolesOnly) ? RoleDefinitions.RoleDirs
                : RoleDefinitions.AllAgentDirs;
            return await PublishAllAsync(endpoint, parsed.GetValue(apply), suffix, dirs, variant);
        });
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    /// <summary>Turn a local agent.md definition into a publishable prompt agent.</summary>
    private static async Task<ProjectsAgentDefinition> BuildPromptAgentAsync(AIProjectClient project, RoleDefinition definition, string agentName)
    {
        var agent = project.AsAIAgent(new ChatClientAgentOptions
        {
            Name = agentName,
            ChatOptions = new ChatOptions
            {
                ModelId = definition.ModelDeployment,
                Instructions = definition.Instructions,
                // A null check, not a truthiness one: temperature 0 is a
                // deliberate setting and must survive.
                Temperature = definition.Temperature is { } temperature ? (float)temperature : null,
            },
        });
        return await agent.ToPromptAgentAsync();
    }

    /// <summary>CreateAgentVersion, retried.</summary>
    /// <remarks>
    /// It intermittently exceeds its read timeout on a freshly provisioned
    /// project. Retrying is safe: a repeat call just adds another version.
    /// </remarks>
    private static async Task<string> CreateVersionAsync(AIProjectClient project, string agentName, ProjectsAgentDefinition promptAgent)
    {
        Exception? lastExc = null;
        for (var attempt = 1; attempt <= PublishAttempts; attempt++)
        {
            try
            {
                var version = (await project.AgentAdministrationClient.CreateAgentVersionAsync(agentName, new ProjectsAgentVersionCreationOptions(promptAgent))).Value;
                return $"published {agentName} version={version.Version ?? "?"}";
            }
            catch (Exception exc)
            {
                // Retried, then reported.
                lastExc = exc;
                if (attempt == PublishAttempts)
                {
                    break;
                }
                var delay = PublishBackoffSeconds * attempt;
                Console.Error.WriteLine($"  [retry {attempt}/{PublishAttempts - 1}] {agentName}: {exc.GetType().Name}; retrying in {delay}s");
                await Task.Delay(TimeSpan.FromSeconds(delay));
            }
        }
        throw new InvalidOperationException($"{agentName} failed after {PublishAttempts} attempts: {lastExc!.GetType().Name}: {lastExc.Message}");
    }

    private static async Task<string> PublishRoleAsync(AIProjectClient project, RoleDefinition definition, string suffix, bool apply, string variant)
    {
        var agentName = AgentName(definition.Role, suffix, variant);
        var promptAgent = await BuildPromptAgentAsync(project, definition, agentName);
        if (!apply)
        {
            return $"[dry-run] would publish {agentName} (model={definition.ModelDeployment})";
        }
        return await CreateVersionAsync(project, agentName, promptAgent);
    }

    /// <summary>Delete only this learner's agents, never anyone else's.</summary>
    private static async Task<int> DeleteAgentsAsync(string endpoint, string suffix, IReadOnlyCollection<string> variants)
    {
        var targets = DeleteTargets(suffix, variants);
        var project = Project(endpoint);
        var present = new HashSet<string>();
        await foreach (var agent in project.AgentAdministrationClient.GetAgentsAsync())
        {
            present.Add(agent.Name ?? "");
        }
        var mine = present.Intersect(targets).Order(StringComparer.Ordinal).ToList();
        if (mine.Count == 0)
        {
            Console.WriteLine($"No agents found for suffix {PyText.Repr(suffix)}. Nothing to delete.");
            var skipped = present.Where(name => name.StartsWith(AgentNamePrefix, StringComparison.Ordinal)).Order(StringComparer.Ordinal).ToList();
            if (skipped.Count > 0)
            {
                Console.WriteLine("Present but not deleted (not an exact match for this suffix):");
                foreach (var name in skipped)
                {
                    Console.WriteLine($"  {name}");
                }
                Console.WriteLine("Pass --variant <name> to delete a variant.");
            }
            return 0;
        }
        foreach (var name in mine)
        {
            await project.AgentAdministrationClient.DeleteAgentAsync(name);
            Console.WriteLine($"deleted {name}");
        }
        return 0;
    }

    private static async Task<int> ListAgentsAsync(string endpoint)
    {
        var found = new List<string>();
        await foreach (var agent in Project(endpoint).AgentAdministrationClient.GetAgentsAsync())
        {
            found.Add(agent.Name ?? "?");
        }
        if (found.Count == 0)
        {
            Console.WriteLine("No agents in this Foundry project.");
            return 0;
        }
        Console.WriteLine($"{found.Count} agent(s) in the project:");
        foreach (var name in found)
        {
            Console.WriteLine($"  {name}");
        }
        return 0;
    }

    private static async Task<int> PublishAllAsync(string endpoint, bool apply, string suffix, IReadOnlyDictionary<string, string> dirs, string variant)
    {
        var roles = RoleDefinitions.LoadAgentDefinitions(dirs);
        if (roles.Count == 0)
        {
            Console.Error.WriteLine("No role definitions resolved. Check that the FOUNDRY_MODEL_DEPLOYMENT_* variables are set.");
            return 2;
        }

        var project = Project(endpoint);
        Console.WriteLine($"Publishing {roles.Count} prompt agent(s) from /agents definitions:");
        var failed = new List<string>();
        foreach (var definition in roles.Values)
        {
            try
            {
                Console.WriteLine("  " + await PublishRoleAsync(project, definition, suffix, apply, variant));
            }
            catch (Exception exc)
            {
                // Keep going: one flaky agent should not block the rest, and
                // re-running only adds a version to whatever already succeeded.
                Console.Error.WriteLine($"  [fail] {definition.Role}: {exc.GetType().Name}: {exc.Message}");
                failed.Add(definition.Role);
            }
        }

        if (failed.Count > 0)
        {
            Console.Error.WriteLine($"\n{failed.Count} agent(s) failed: {string.Join(", ", failed)}.\nRe-run the same command; publishing is safe to repeat.");
            return 1;
        }

        Console.WriteLine(apply ? "\nDone. These appear in the Foundry portal under Agents." : "\nDry run. Re-run with --apply to publish.");
        return 0;
    }

    private static AIProjectClient Project(string endpoint) => new(new Uri(endpoint), Credentials.Default());

    private static string? RequireEndpoint()
    {
        var endpoint = Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") is { Length: > 0 } project
            ? project
            : Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_ENDPOINT") ?? "";
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. Run .\\dotnet\\scripts\\populate-env.ps1 first.");
            return null;
        }
        return endpoint;
    }

    private static void LoadEnv()
    {
        if (!File.Exists(EnvFile))
        {
            return;
        }
        foreach (var raw in PyText.SplitLines(File.ReadAllText(EnvFile)))
        {
            var line = PyText.Strip(raw);
            if (line.Length > 0 && !line.StartsWith('#') && line.Contains('='))
            {
                var at = line.IndexOf('=');
                var key = PyText.Strip(line[..at]);
                if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(key)))
                {
                    Environment.SetEnvironmentVariable(key, PyText.Strip(line[(at + 1)..]));
                }
            }
        }
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;

    [GeneratedRegex(@"^[a-z0-9-]{1,24}\z", RegexOptions.CultureInvariant)]
    private static partial Regex SuffixRe();

    [GeneratedRegex(@"^[a-z0-9-]{1,16}\z", RegexOptions.CultureInvariant)]
    private static partial Regex VariantRe();
}
