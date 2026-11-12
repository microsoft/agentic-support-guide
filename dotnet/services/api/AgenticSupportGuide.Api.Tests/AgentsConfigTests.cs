using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;
using YamlDotNet.Serialization;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Tests for the /agents definitions and remote-agent binding metadata.</summary>
/// <remarks>
/// The agent folders are read where the app reads them,
/// <see cref="PromptEnvelope.AgentsDir"/>: the copy of the repo root's
/// <c>agents/</c> that ships next to the app. The Python tests that read the
/// app's own <c>*.py</c> source read this track's C# source instead.
/// </remarks>
public sealed class AgentsConfigTests
{
    private static readonly string[] AgentIds = ["data-analyst", "support-recommender", "validator"];

    // This track's equivalent of the Python app folder: the API project's source.
    private static readonly string ApiSourceDir = Path.Combine(Conformance.Goldens.RepoRoot, "dotnet", "services", "api", "AgenticSupportGuide.Api");

    public static TheoryData<string> AgentIdCases() => [.. AgentIds];

    public static TheoryData<string> AgentIdAndExplainerCases() => [.. AgentIds, "support-explainer"];

    [Fact]
    public void Each_agent_folder_has_required_files()
    {
        foreach (var agentId in AgentIds)
        {
            var agentDir = Path.Combine(PromptEnvelope.AgentsDir, agentId);
            Assert.True(Directory.Exists(agentDir));
            Assert.True(File.Exists(Path.Combine(agentDir, "agent.md")));
            Assert.True(File.Exists(Path.Combine(agentDir, "manifest.yaml")));
            Assert.True(File.Exists(Path.Combine(agentDir, "schemas", "input.schema.json")));
            Assert.True(File.Exists(Path.Combine(agentDir, "schemas", "output.schema.json")));
        }
    }

    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Agent_manifest_has_required_top_level_keys(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var m = assets.Manifest;
        Assert.True(Truthy(m.GetValueOrDefault("id")));
        Assert.True(Truthy(m.GetValueOrDefault("version")));
        Assert.True(Truthy(m.GetValueOrDefault("runtime")));
        Assert.True(Truthy(PromptEnvelope.Section(m, "contracts").GetValueOrDefault("input")));
        Assert.True(Truthy(PromptEnvelope.Section(m, "contracts").GetValueOrDefault("output")));
        Assert.True(Truthy(m.GetValueOrDefault("handoff")));
        Assert.True(Truthy(m.GetValueOrDefault("safety")));
    }

    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Agent_manifest_has_foundry_runtime_block(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var foundry = PromptEnvelope.Section(assets.Manifest, "foundry");
        foreach (var key in new[] { "model_deployment_env", "response_format" })
        {
            Assert.True(Truthy(foundry.GetValueOrDefault(key)), $"{agentId}: foundry.{key} missing");
        }
    }

    /// <summary>Published names are learner-suffixed at publish time, never in the manifest.</summary>
    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Agent_manifest_has_no_persisted_agent_name(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var foundry = PromptEnvelope.Section(assets.Manifest, "foundry");
        Assert.DoesNotContain("foundry_agent_name", foundry);
    }

    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Agent_local_schemas_are_valid_json(string agentId)
    {
        foreach (var name in new[] { "input.schema.json", "output.schema.json" })
        {
            var path = Path.Combine(PromptEnvelope.AgentsDir, agentId, "schemas", name);
            var data = JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8))!.AsObject();
            Assert.Equal("object", data["type"]?.GetValue<string>());
        }
        // The output schema is sent to the model as-is, so it carries no
        // `$schema` keyword; the Python track's test_conformance holds it equal
        // to the contract.
        var input = JsonNode.Parse(File.ReadAllText(Path.Combine(PromptEnvelope.AgentsDir, agentId, "schemas", "input.schema.json"), Encoding.UTF8))!.AsObject();
        Assert.False(string.IsNullOrEmpty(input["$schema"]?.GetValue<string>()));
    }

    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Composed_instructions_include_agent_md_body_and_envelope(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var instructions = PromptEnvelope.ComposeInstructions(
            assets.AgentMdBody, frontmatter: assets.AgentMdFrontmatter);
        Assert.Contains(PyText.SplitLines(assets.AgentMdBody)[0], instructions, StringComparison.Ordinal);
        Assert.Contains(PyText.Strip(PromptEnvelope.RuntimeEnvelope), instructions, StringComparison.Ordinal);
    }

    /// <summary>A text-mode agent told to "return JSON only" answers the playground in JSON.</summary>
    [Theory]
    [MemberData(nameof(AgentIdAndExplainerCases))]
    public void Json_contract_follows_the_declared_response_format(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var responseFormat = PromptEnvelope.Section(assets.Manifest, "foundry").GetValueOrDefault("response_format", "json");
        var declared = Truthy(responseFormat) ? $"{responseFormat}" : "json";
        var instructions = PromptEnvelope.ComposeInstructions(
            assets.AgentMdBody,
            frontmatter: assets.AgentMdFrontmatter,
            responseFormat: declared);
        // Always present, whatever the output shape.
        Assert.Contains("<<<UNTRUSTED_DATA>>>", instructions, StringComparison.Ordinal);
        Assert.Contains(Determinations.PolicyNounPhrase, instructions, StringComparison.Ordinal);

        var wantsJson = PyText.Lower(PyText.Strip(declared)) != "text";
        Assert.Equal(wantsJson, instructions.Contains("Return JSON only", StringComparison.Ordinal));
        Assert.Equal(wantsJson, instructions.Contains("satisfy the referenced output schema", StringComparison.Ordinal));
    }

    /// <summary>The output contract lives in frontmatter; dropping it yields off-contract JSON.</summary>
    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Composed_instructions_carry_frontmatter_rules(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var instructions = PromptEnvelope.ComposeInstructions(
            assets.AgentMdBody, frontmatter: assets.AgentMdFrontmatter);
        foreach (var key in new[] { "constraints", "safety_rules", "grounding_rules" })
        {
            foreach (var item in assets.AgentMdFrontmatter.GetValueOrDefault(key) as IEnumerable<object?> ?? [])
            {
                Assert.True(instructions.Contains(PyText.Strip($"{item}"), StringComparison.Ordinal), $"{agentId}: dropped {key} -> {item}");
            }
        }
    }

    [Fact]
    public void Data_analyst_instructions_state_the_output_shape()
    {
        var assets = PromptEnvelope.LoadAgentAssets("data-analyst");
        var instructions = PromptEnvelope.ComposeInstructions(
            assets.AgentMdBody, frontmatter: assets.AgentMdFrontmatter);
        foreach (var token in new[] { "contract_version", "analysis", "detected_need", "evidence_bullets" })
        {
            Assert.Contains(token, instructions, StringComparison.Ordinal);
        }
    }

    [Theory]
    [MemberData(nameof(AgentIdCases))]
    public void Instructions_hash_is_stable_across_whitespace(string agentId)
    {
        var assets = PromptEnvelope.LoadAgentAssets(agentId);
        var ihash1 = PromptEnvelope.InstructionsHash(
            PromptEnvelope.ComposeInstructions(assets.AgentMdBody, frontmatter: assets.AgentMdFrontmatter));
        var crlfBody = assets.AgentMdBody.Replace("\n", "\r\n", StringComparison.Ordinal);
        var ihash2 = PromptEnvelope.InstructionsHash(
            PromptEnvelope.ComposeInstructions(crlfBody, frontmatter: assets.AgentMdFrontmatter));
        Assert.Equal(ihash1, ihash2);
    }

    /// <summary>Scans this track's app source: the API project's C# files.</summary>
    [Fact]
    public void App_source_has_no_hardcoded_role_prompt()
    {
        string[] forbiddenSignals =
        [
            "You are the Data Analyst Agent",
            "You are the Support Recommendation Agent",
            "You are the Validator Agent",
        ];
        var sourceFiles = SourceFiles(ApiSourceDir, "*.cs");
        Assert.NotEmpty(sourceFiles);
        foreach (var sourceFile in sourceFiles)
        {
            var text = File.ReadAllText(sourceFile, Encoding.UTF8);
            foreach (var signal in forbiddenSignals)
            {
                Assert.DoesNotContain(signal, text, StringComparison.Ordinal);
            }
        }
    }

    /// <summary>Python's <c>agent.py</c> modules are the <c>*Agent.cs</c> files, and its relative imports are using directives.</summary>
    [Fact]
    public void Agents_do_not_import_each_other()
    {
        var agentsRoot = Path.Combine(ApiSourceDir, "Agents");
        var agentFiles = SourceFiles(agentsRoot, "*Agent.cs");
        Assert.NotEmpty(agentFiles);
        foreach (var agentFile in agentFiles)
        {
            var text = File.ReadAllText(agentFile, Encoding.UTF8);
            foreach (var forbidden in new[]
            {
                "using AgenticSupportGuide.Api.Agents.DataAnalyst",
                "using AgenticSupportGuide.Api.Agents.SupportRecommender",
                "using AgenticSupportGuide.Api.Agents.Validator",
            })
            {
                Assert.DoesNotContain(forbidden, text, StringComparison.Ordinal);
            }
        }
    }

    /// <summary>
    /// The agents share the API's root namespace, so using one of its types needs
    /// no using directive: the internals are forbidden by name, outside comments.
    /// </summary>
    [Fact]
    public void Agents_do_not_import_api_internals()
    {
        var agentsRoot = Path.Combine(ApiSourceDir, "Agents");
        var internals = ApiInternals();
        Assert.Contains("Recommendation", internals);
        var sourceFiles = SourceFiles(agentsRoot, "*.cs");
        Assert.NotEmpty(sourceFiles);
        foreach (var sourceFile in sourceFiles)
        {
            var code = CodeWithoutCommentLines(sourceFile);
            foreach (var forbidden in internals)
            {
                Assert.DoesNotMatch(new Regex($@"\b{forbidden}\b"), code);
            }
        }
    }

    /// <summary>
    /// The Python tokens as this track spells them: the <c>OpenAI</c> namespace,
    /// and <c>CompleteChat</c> for <c>chat.completions</c>. Matched without case,
    /// so <c>openai.</c> still catches a hand-built api.openai.com address.
    /// </summary>
    [Fact]
    public void No_direct_model_calls_outside_the_sdk_boundary()
    {
        string[] forbidden = ["AzureOpenAI", "openai.", "CompleteChat"];
        string[] permitted = [Path.Combine(ApiSourceDir, "FoundryAgents", "MafClient.cs")];
        var sourceFiles = SourceFiles(ApiSourceDir, "*.cs");
        Assert.NotEmpty(sourceFiles);
        foreach (var sourceFile in sourceFiles)
        {
            if (permitted.Contains(sourceFile))
            {
                continue;
            }
            var text = File.ReadAllText(sourceFile, Encoding.UTF8);
            foreach (var token in forbidden)
            {
                Assert.False(text.Contains(token, StringComparison.OrdinalIgnoreCase), $"{sourceFile}: forbidden reference to '{token}'");
            }
        }
    }

    [Fact]
    public void All_manifests_load_via_yaml()
    {
        foreach (var agentId in AgentIds)
        {
            var text = File.ReadAllText(Path.Combine(PromptEnvelope.AgentsDir, agentId, "manifest.yaml"), Encoding.UTF8);
            var data = new DeserializerBuilder().Build().Deserialize<object>(text);
            Assert.IsAssignableFrom<IDictionary<object, object>>(data);
        }
    }

    /// <summary>Python's truthiness, for a value read from YAML.</summary>
    private static bool Truthy(object? value) => value switch
    {
        null => false,
        string text => text.Length > 0,
        System.Collections.ICollection collection => collection.Count > 0,
        _ => true,
    };

    /// <summary><c>rglob(pattern)</c> over a source folder, without the build output.</summary>
    private static List<string> SourceFiles(string root, string pattern) =>
        Directory.EnumerateFiles(root, pattern, SearchOption.AllDirectories)
            .Where(path => !Path.GetRelativePath(ApiSourceDir, path).Split(Path.DirectorySeparatorChar).Any(part => part is "bin" or "obj"))
            .Order(StringComparer.Ordinal)
            .ToList();

    // app.main, app.workflows, app.models, app.plans_store and app.runtime_audit,
    // as this track names them.
    private static List<string> ApiInternals() =>
    [
        "Program",
        "Workflows",
        .. DeclaredTypes(Path.Combine(ApiSourceDir, "Models.cs")),
        "SavedPlansStore",
        "RuntimeAuditLog",
    ];

    private static IEnumerable<string> DeclaredTypes(string path) =>
        Regex.Matches(
                File.ReadAllText(path, Encoding.UTF8),
                @"^public\s+(?:(?:sealed|static|abstract|partial)\s+)*(?:class|record|struct|interface|enum)\s+(\w+)",
                RegexOptions.Multiline)
            .Select(match => match.Groups[1].Value);

    // Comments here are whole lines, and may name a type the code does not use.
    private static string CodeWithoutCommentLines(string path) =>
        string.Join("\n", File.ReadAllLines(path, Encoding.UTF8).Where(line => !line.TrimStart().StartsWith("//", StringComparison.Ordinal)));
}
