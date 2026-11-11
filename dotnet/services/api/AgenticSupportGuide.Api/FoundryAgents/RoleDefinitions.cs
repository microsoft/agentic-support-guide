using System.Globalization;

namespace AgenticSupportGuide.Api.FoundryAgents;

/// <summary>
/// Role definitions from agent.md + per-role model deployment environment variables.
/// </summary>
/// <remarks>
/// A role is available when its definition file loads and its model deployment
/// environment variable is set - there is no server-side agent to bind to.
/// </remarks>
public static class RoleDefinitions
{
    // Coordinator roles. The three-agent workflow requires all of these.
    public static readonly IReadOnlyDictionary<string, string> RoleDirs = new Dictionary<string, string>
    {
        ["data-analyst"] = "data-analyst-agent",
        ["support-recommender"] = "support-recommendation-agent",
        ["validator"] = "validator-agent",
    };

    // Standalone workshop agents published to Foundry as prompt agents. They are
    // not part of the workflow, so readiness must not depend on them.
    public static readonly IReadOnlyDictionary<string, string> WorkshopAgentDirs = new Dictionary<string, string>
    {
        ["support-explainer"] = "support-explainer-agent",
    };

    public static readonly IReadOnlyList<string> RequiredRoles = [.. RoleDirs.Values];

    public static readonly IReadOnlyDictionary<string, string> AllAgentDirs =
        RoleDirs.Concat(WorkshopAgentDirs).ToDictionary(kv => kv.Key, kv => kv.Value);

    /// <summary>Role -> environment variable holding its model deployment name.</summary>
    public static Dictionary<string, string> ModelDeploymentEnvNames(IReadOnlyDictionary<string, string>? dirs = null)
    {
        var names = new Dictionary<string, string>();
        foreach (var (agentDir, role) in dirs ?? RoleDirs)
        {
            var envName = DeploymentEnvName(PromptEnvelope.LoadAgentAssets(agentDir));
            if (envName.Length > 0)
            {
                names[role] = envName;
            }
        }
        return names;
    }

    /// <summary>Environment variable names a learner still has to populate for the workflow.</summary>
    public static List<string> MissingModelDeployments() =>
        ModelDeploymentEnvNames().Values
            .Where(name => string.IsNullOrEmpty(Environment.GetEnvironmentVariable(name)))
            .Order(StringComparer.Ordinal)
            .ToList();

    public static Dictionary<string, RoleDefinition> LoadAgentDefinitions(IReadOnlyDictionary<string, string> dirs)
    {
        var definitions = new Dictionary<string, RoleDefinition>();
        foreach (var (agentDir, role) in dirs)
        {
            var assets = PromptEnvelope.LoadAgentAssets(agentDir);
            var foundry = PromptEnvelope.Section(assets.Manifest, "foundry");
            var envName = DeploymentEnvName(assets);
            var deployment = envName.Length > 0 ? Environment.GetEnvironmentVariable(envName) ?? "" : "";
            if (deployment.Length == 0)
            {
                continue;
            }
            definitions[role] = new RoleDefinition(
                Role: role,
                Instructions: PromptEnvelope.ComposeInstructions(
                    assets.AgentMdBody,
                    assets.AgentMdFrontmatter,
                    PromptEnvelope.DeclaredResponseFormat(assets.Manifest)),
                ModelDeployment: deployment,
                Temperature: foundry.TryGetValue("temperature", out var t) && t is not null ? double.Parse(t.ToString()!, CultureInfo.InvariantCulture) : null,
                MaxOutputTokens: foundry.TryGetValue("max_output_tokens", out var m) && m is not null ? int.Parse(m.ToString()!, CultureInfo.InvariantCulture) : null,
                ResponseSchema: PromptEnvelope.LoadResponseSchema(assets));
        }
        return definitions;
    }

    /// <summary>Workflow roles only.</summary>
    public static Dictionary<string, RoleDefinition> LoadRoleDefinitions() => LoadAgentDefinitions(RoleDirs);

    private static string DeploymentEnvName(AgentAssets assets) =>
        PromptEnvelope.Section(assets.Manifest, "foundry").TryGetValue("model_deployment_env", out var value) ? value?.ToString() ?? "" : "";
}
