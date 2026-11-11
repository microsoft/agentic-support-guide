#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Validate the agent definitions in /agents. No network, no deployment.
//
// GenAIOps boundary: agent behavior is defined by `/agents/<id>/agent.md` and
// `manifest.yaml`, versioned in git and loaded by the app at runtime. There is
// nothing to deploy - the runtime builds ephemeral agents per call - so this
// script only checks that the definitions are well formed and that every
// schema a manifest names exists in that agent's `schemas/` folder.
//
// Infrastructure (DevOps) is provisioned separately by Terraform in
// `/dotnet/infra` and never creates agents.
//
// Usage:
//   dotnet run dotnet/scripts/validate_agent_definitions.cs                            # offline validation
//   dotnet run dotnet/scripts/validate_agent_definitions.cs -- --check-connectivity

using System.Collections;
using System.CommandLine;
using System.Runtime.CompilerServices;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;
using Azure.AI.Projects;

return await ValidateAgentDefinitions.MainAsync(args);

public static class ValidateAgentDefinitions
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string RepoRoot = Path.GetFullPath(Path.Combine(TrackRoot, ".."));
    private static readonly string AgentsDir = Path.Combine(RepoRoot, "agents");
    private static readonly string EnvFile = Path.Combine(TrackRoot, "services", "api", ".env");

    private static readonly string[] RequiredManifestKeys = ["id", "name", "version", "runtime", "contracts", "handoff", "safety"];
    private static readonly string[] RequiredFoundryKeys = ["model_deployment_env", "response_format"];
    private static readonly string[] RequiredContractSides = ["input", "output"];
    private static readonly string[] RequiredContractKeys = ["schema_ref", "schema_version"];

    public static async Task<int> MainAsync(string[] args)
    {
        var checkConnectivity = new Option<bool>("--check-connectivity") { Description = "Live check: verify the Foundry project endpoint and credential work." };
        var showInstructions = new Option<string?>("--show-instructions")
        {
            Description = "Print the composed instructions for one agent, for pasting into the portal.",
            HelpName = "AGENT",
        };
        var command = new RootCommand("Validate the agent definitions in /agents. No network, no deployment.") { checkConnectivity, showInstructions };
        command.SetAction(async (parsed, _) =>
        {
            LoadEnvFile();

            if (!Directory.Exists(AgentsDir))
            {
                Console.Error.WriteLine($"ERROR: /agents directory not found at {AgentsDir}");
                return 1;
            }

            if (parsed.GetValue(showInstructions) is { Length: > 0 } agent)
            {
                return ShowInstructions(agent);
            }

            var allErrors = ValidateAll();
            if (allErrors.Count > 0)
            {
                Console.Error.WriteLine($"\n{allErrors.Count} problem(s) found.");
                return 1;
            }

            if (parsed.GetValue(checkConnectivity))
            {
                return await CheckConnectivityAsync();
            }

            Console.WriteLine(
                "\nAll agent definitions are valid. Publish them to Foundry with:\n"
                + "  dotnet run dotnet/scripts/publish_prompt_agents.cs -- --suffix <your-alias> --apply");
            return 0;
        });
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    /// <summary>Read dotnet/services/api/.env; real environment variables win.</summary>
    private static void LoadEnvFile()
    {
        if (!File.Exists(EnvFile))
        {
            return;
        }
        foreach (var raw in PyText.SplitLines(File.ReadAllText(EnvFile)))
        {
            var line = PyText.Strip(raw);
            if (line.Length == 0 || line.StartsWith('#') || !line.Contains('='))
            {
                continue;
            }
            var at = line.IndexOf('=');
            var key = PyText.Strip(line[..at]);
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(key)))
            {
                Environment.SetEnvironmentVariable(key, PyText.Strip(line[(at + 1)..]).Trim('"').Trim('\''));
            }
        }
    }

    private static List<string> AllAgents() =>
        [.. Directory.GetDirectories(AgentsDir)
            .Where(dir => !Path.GetFileName(dir).StartsWith('.'))
            .Order(StringComparer.Ordinal)];

    // Python's truthiness, which the checks below were written against.
    private static bool Truthy(object? value) => value switch
    {
        null => false,
        string text => text.Length > 0,
        ICollection collection => collection.Count > 0,
        _ => true,
    };

    private static object? Get(IReadOnlyDictionary<string, object?> mapping, string key) =>
        mapping.TryGetValue(key, out var value) ? value : null;

    private static (IReadOnlyDictionary<string, object?> Manifest, List<string> Errors) ValidateManifest(string agentDir)
    {
        var name = Path.GetFileName(agentDir);
        var errors = new List<string>();
        var manifestPath = Path.Combine(agentDir, "manifest.yaml");
        if (!File.Exists(manifestPath))
        {
            return (new Dictionary<string, object?>(), [$"{name}: manifest.yaml not found"]);
        }

        var manifest = PromptEnvelope.LoadYamlMapping(File.ReadAllText(manifestPath));
        var foundry = PromptEnvelope.Section(manifest, "foundry");
        var isTextAgent = Get(foundry, "response_format") as string == "text";

        foreach (var key in RequiredManifestKeys)
        {
            if (key == "contracts" && isTextAgent)
            {
                continue;
            }
            if (!manifest.ContainsKey(key))
            {
                errors.Add($"{name}: manifest missing '{key}'");
            }
        }

        foreach (var key in RequiredFoundryKeys)
        {
            if (!Truthy(Get(foundry, key)))
            {
                errors.Add($"{name}: manifest.foundry missing '{key}'");
            }
        }

        // Persisted-agent leftovers must not come back.
        if (foundry.ContainsKey("foundry_agent_name"))
        {
            errors.Add(
                $"{name}: manifest.foundry.foundry_agent_name names a persisted "
                + "agent; agents are ephemeral and this key must be removed");
        }

        var contracts = PromptEnvelope.Section(manifest, "contracts");
        // A text agent answers in prose, so there is no schema for it to honour.
        // Requiring one produced a manifest that borrowed the data analyst's.
        if (isTextAgent)
        {
            if (contracts.Count > 0)
            {
                errors.Add($"{name}: response_format is text, so contracts must be omitted");
            }
        }
        else
        {
            foreach (var side in RequiredContractSides)
            {
                var block = PromptEnvelope.Section(contracts, side);
                foreach (var key in RequiredContractKeys)
                {
                    if (!Truthy(Get(block, key)))
                    {
                        errors.Add($"{name}: contracts.{side} missing '{key}'");
                    }
                }
                if (Get(block, "schema_ref") is string reference && reference.Length > 0 && !File.Exists(Path.Combine(agentDir, reference)))
                {
                    errors.Add($"{name}: contracts.{side}.schema_ref not found in agents/{name} -> {reference}");
                }
            }
        }

        return (manifest, errors);
    }

    /// <summary>Compose instructions the way the runtime does and sanity-check them.</summary>
    private static (string Instructions, List<string> Errors) ValidateInstructions(string agentDir)
    {
        var name = Path.GetFileName(agentDir);
        var errors = new List<string>();
        var assets = PromptEnvelope.LoadAgentAssets(name);
        var instructions = PromptEnvelope.ComposeInstructions(
            assets.AgentMdBody,
            assets.AgentMdFrontmatter,
            PromptEnvelope.DeclaredResponseFormat(assets.Manifest));
        if (PyText.Strip(assets.AgentMdBody).Length == 0)
        {
            errors.Add($"{name}: agent.md body is empty");
        }
        // The behavioural rules live in frontmatter; dropping them silently
        // produces plausible but off-contract model output.
        foreach (var key in (ReadOnlySpan<string>)["constraints", "safety_rules"])
        {
            if (!Truthy(Get(assets.AgentMdFrontmatter, key)))
            {
                errors.Add($"{name}: agent.md frontmatter missing '{key}'");
            }
        }
        return (instructions, errors);
    }

    private static int ShowInstructions(string name)
    {
        var names = AllAgents().Select(Path.GetFileName).ToList();
        if (!names.Contains(name))
        {
            Console.Error.WriteLine($"ERROR: unknown agent '{name}'. Choose one of: {string.Join(", ", names)}");
            return 1;
        }
        var (instructions, _) = ValidateInstructions(Path.Combine(AgentsDir, name));
        Console.WriteLine(instructions);
        return 0;
    }

    /// <summary>Validate every agent, printing one line each. Returns all errors.</summary>
    private static List<string> ValidateAll()
    {
        var allErrors = new List<string>();
        var agents = AllAgents();
        Console.WriteLine($"Validating {agents.Count} agent definition(s):");
        foreach (var agentDir in agents)
        {
            var (manifest, errors) = ValidateManifest(agentDir);
            var (instructions, more) = ValidateInstructions(agentDir);
            errors.AddRange(more);
            allErrors.AddRange(errors);
            if (errors.Count > 0)
            {
                foreach (var error in errors)
                {
                    Console.WriteLine($"  [FAIL] {error}");
                }
                continue;
            }
            var foundry = PromptEnvelope.Section(manifest, "foundry");
            var envName = Get(foundry, "model_deployment_env")?.ToString() ?? "";
            var state = Environment.GetEnvironmentVariable(envName) is { Length: > 0 } value ? value : "<unset>";
            Console.WriteLine(
                $"  [ok]   {Path.GetFileName(agentDir),-22} model_env={envName} ({state}) "
                + $"instructions_hash={PromptEnvelope.InstructionsHash(instructions)[..12]}");
        }
        return allErrors;
    }

    private static async Task<int> CheckConnectivityAsync()
    {
        var endpoint = Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") is { Length: > 0 } project
            ? project
            : Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_ENDPOINT") ?? "";
        if (endpoint.Length == 0)
        {
            Console.Error.WriteLine("\nAZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set. Run .\\dotnet\\scripts\\populate-env.ps1 first.");
            return 2;
        }
        try
        {
            var client = new AIProjectClient(new Uri(endpoint), Credentials.Default());
            await foreach (var _ in client.Deployments.GetDeploymentsAsync())
            {
            }
        }
        catch (Exception exc)
        {
            // Surfaced as a learner-facing hint.
            Console.Error.WriteLine($"\n[fail] Could not reach the Foundry project: {exc.GetType().Name}");
            Console.Error.WriteLine(
                "       Check: 'az login', the correct subscription, and that RBAC "
                + "has propagated (can take a few minutes after terraform apply).");
            return 2;
        }
        Console.WriteLine("\n[ok] Foundry project endpoint reachable with the current credential.");
        return 0;
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;
}
