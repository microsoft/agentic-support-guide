#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Provision Foundry IQ: index, documents, knowledge source, knowledge base.
//
// Module 6. This is the real thing, not a portal walkthrough: the index it
// builds is what the running API queries once EVIDENCE_SOURCE=foundry_iq.
//
// Documents are PUSHED straight into the index over the data plane. That is
// deliberate - blob upload is blocked by Azure Policy in many tenants, and
// pushing also lets us define `dealer_group_id` as a real filterable field
// instead of leaving it as prose inside a markdown blob.
//
// Order matters: index -> documents -> knowledge source -> knowledge base.
//
// Usage:
//     dotnet run dotnet/scripts/provision_foundry_iq.cs -- --suffix <your-alias>            # dry run
//     dotnet run dotnet/scripts/provision_foundry_iq.cs -- --suffix <your-alias> --apply
//     dotnet run dotnet/scripts/provision_foundry_iq.cs -- --suffix <your-alias> --query "..."
//     dotnet run dotnet/scripts/provision_foundry_iq.cs -- --suffix <your-alias> --delete

using System.CommandLine;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.Evidence;
using AgenticSupportGuide.Api.Parity;
using Azure;
using Azure.Search.Documents;
using Azure.Search.Documents.Indexes;
using Azure.Search.Documents.Indexes.Models;
using Azure.Search.Documents.Models;

// The tests compile this file too, and call its methods directly.
#if !UNDER_TEST
return await ProvisionFoundryIq.MainAsync(args);
#endif

public static partial class ProvisionFoundryIq
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string EnvFile = Path.Combine(TrackRoot, "services", "api", ".env");
    private const string SemanticConfig = "asg-semantic";

    /// <summary>Every Foundry IQ object is learner-scoped.</summary>
    public static Dictionary<string, string> Names(string suffix) => new()
    {
        ["index"] = $"asg-evidence-{suffix}",
        ["source"] = $"asg-ks-{suffix}",
        ["blob_source"] = $"asg-ks-blob-{suffix}",
        ["web_source"] = $"asg-ks-web-{suffix}",
        ["base"] = $"asg-kb-{suffix}",
    };

    // Web IQ is an allowlist, not open browsing: the agent may only reach these
    // addresses. Everything else is unreachable regardless of what it is asked.
    // Addresses may be a bare domain or a specific path; include_subpages lets
    // retrieval follow below that path.
    // Public sources a dealer group can legitimately benchmark against. Each is
    // path-scoped because `include_subpages` crawls everything beneath the address.
    public static readonly string[] DefaultWebDomains =
    [
        "https://www.census.gov/econ/indviz/auto/main.html",
        "https://www.nada.org/nada/research-data/nada-data",
        "https://www.nada.org/nada/market-beat",
        "https://www.fueleconomy.gov/feg/label/",
    ];

    private static readonly string[] SourceDataFields =
        ["citation_id", "dealer_group_id", "category", "source_title", "evidence_summary", "source_type", "section_or_page", "source_ref"];

    /// <summary>Everything the four provisioning steps need, resolved up front.</summary>
    /// <remarks>
    /// Built once in <see cref="BuildPlanAsync"/> so the dry run prints exactly
    /// what <c>--apply</c> would create -- there is no second code path that
    /// could drift.
    /// </remarks>
    private sealed record ProvisionPlan(
        string Endpoint,
        string Suffix,
        List<Dictionary<string, string>> Docs,
        string[] WebDomains,
        string BlobContainer,
        string BlobResourceId,
        string AoaiEndpoint,
        string AoaiDeployment,
        string AoaiModel = "gpt-4.1-mini")
    {
        public Dictionary<string, string> Names => ProvisionFoundryIq.Names(Suffix);
    }

    public static async Task<int> MainAsync(string[] args)
    {
        LoadEnv();

        var apply = new Option<bool>("--apply") { Description = "Create index, documents, source, base." };
        var query = new Option<string?>("--query") { Description = "Retrieve against the knowledge base and print citations." };
        var delete = new Option<bool>("--delete") { Description = "Remove this learner's IQ objects." };
        var suffixOption = new Option<string>("--suffix")
        {
            Description = "Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
            DefaultValueFactory = _ => Environment.GetEnvironmentVariable("WORKSHOP_LEARNER_SUFFIX") ?? "",
        };
        var webDomains = new Option<string>("--web-domains")
        {
            Description = "Comma-separated domain allowlist for the Web IQ source. The agent "
                + $"may reach nothing else. Empty disables it. Default: {string.Join(',', DefaultWebDomains)}",
            DefaultValueFactory = _ => string.Join(',', DefaultWebDomains),
        };
        var blobContainer = new Option<string>("--blob-container")
        {
            Description = "Blob container for the Azure blob source. Empty disables it.",
            DefaultValueFactory = _ => Environment.GetEnvironmentVariable("KNOWLEDGE_CONTAINER") ?? "",
        };
        var command = new RootCommand("Provision Foundry IQ: index, documents, knowledge source, knowledge base.")
        {
            apply, query, delete, suffixOption, webDomains, blobContainer,
        };
        command.SetAction(async (parsed, _) =>
        {
            var suffix = PyText.Lower(PyText.Strip(parsed.GetValue(suffixOption) ?? ""));
            if (suffix.Length == 0 || !SuffixRe().IsMatch(suffix))
            {
                Console.Error.WriteLine("Pass --suffix <your-alias> (a-z, 0-9, '-') or set WORKSHOP_LEARNER_SUFFIX.");
                return 2;
            }

            var endpoint = Environment.GetEnvironmentVariable("AZURE_SEARCH_ENDPOINT") ?? "";
            if (endpoint.Length == 0)
            {
                Console.Error.WriteLine("AZURE_SEARCH_ENDPOINT is not set. Run .\\dotnet\\scripts\\populate-env.ps1.");
                return 2;
            }

            if (parsed.GetValue(delete))
            {
                return await DeleteAsync(endpoint, suffix);
            }
            if (parsed.GetValue(query) is { Length: > 0 } question)
            {
                return await QueryAsync(endpoint, suffix, question);
            }

            var plan = await BuildPlanAsync(endpoint, suffix, parsed.GetValue(webDomains) ?? "", parsed.GetValue(blobContainer) ?? "");
            if (plan is null)
            {
                return 2;
            }
            PrintPlan(plan);
            if (!parsed.GetValue(apply))
            {
                Console.WriteLine("\nDry run. Nothing created. Re-run with --apply.");
                return 0;
            }
            return await ApplyAsync(plan);
        });
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    /// <summary>Knowledge bases need the account endpoint, not the project endpoint.</summary>
    private static string AoaiEndpoint()
    {
        var project = Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") ?? "";
        var at = project.IndexOf("/api/projects/", StringComparison.Ordinal);
        var host = at >= 0 ? project[..at] : project;
        return host.Replace(".services.ai.azure.com", ".openai.azure.com", StringComparison.Ordinal);
    }

    /// <summary>Blob sources authenticate with a managed identity, not a key.</summary>
    private static string StorageResourceId()
    {
        var infra = Path.Combine(TrackRoot, "infra");
        try
        {
            using var terraform = Process.Start(new ProcessStartInfo("terraform", [$"-chdir={infra}", "output", "-raw", "knowledge_storage_account_id"])
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            })!;
            var output = terraform.StandardOutput.ReadToEndAsync();
            if (!terraform.WaitForExit(TimeSpan.FromSeconds(60)))
            {
                terraform.Kill(entireProcessTree: true);
                return "";
            }
            var value = PyText.Strip(output.Result);
            return value.StartsWith("/subscriptions/", StringComparison.Ordinal) ? value : "";
        }
        catch (System.ComponentModel.Win32Exception)
        {
            return "";
        }
    }

    private static SearchIndex BuildIndex(string indexName) => new(indexName)
    {
        Fields =
        {
            new SimpleField("citation_id", SearchFieldDataType.String) { IsKey = true },
            // Filterable, so dealer group isolation is enforced by the engine
            // rather than by hoping the model respects an instruction.
            new SimpleField("dealer_group_id", SearchFieldDataType.String) { IsFilterable = true, IsFacetable = true },
            new SimpleField("category", SearchFieldDataType.String) { IsFilterable = true, IsFacetable = true },
            new SearchableField("source_title"),
            new SearchableField("evidence_summary"),
            new SimpleField("source_type", SearchFieldDataType.String) { IsFilterable = true },
            new SimpleField("section_or_page", SearchFieldDataType.String),
            new SimpleField("source_ref", SearchFieldDataType.String),
        },
        SemanticSearch = new SemanticSearch
        {
            Configurations =
            {
                new SemanticConfiguration(SemanticConfig, new SemanticPrioritizedFields
                {
                    TitleField = new SemanticField("source_title"),
                    ContentFields = { new SemanticField("evidence_summary") },
                }),
            },
        },
    };

    /// <summary>The same synthetic evidence the fixtures serve, as index documents.</summary>
    private static async Task<List<Dictionary<string, string>>> DocumentsAsync()
    {
        var retriever = new FixtureEvidenceRetriever();
        var docs = new List<Dictionary<string, string>>();
        foreach (var group in FixtureEvidenceRetriever.ListAvailableDealerGroups())
        {
            foreach (var category in AgenticSupportGuide.Api.MockData.CategoryIds)
            {
                var bundle = await retriever.RetrieveAsync(new EvidenceRequest(group, category, DetectedNeedHint: ""));
                foreach (var c in bundle.Citations)
                {
                    docs.Add(new Dictionary<string, string>
                    {
                        ["citation_id"] = c.CitationId,
                        ["dealer_group_id"] = c.DealerGroupId,
                        ["category"] = category,
                        ["source_title"] = c.SourceTitle,
                        ["evidence_summary"] = c.EvidenceSummary,
                        ["source_type"] = c.SourceType,
                        ["section_or_page"] = c.SectionOrPage,
                        ["source_ref"] = c.SourceRef,
                    });
                }
            }
        }
        return docs;
    }

    /// <summary>Replace the index contents. Returns the number of failed operations.</summary>
    /// <remarks>
    /// Stale keys are deleted first. Uploading is an upsert, so re-running
    /// after the fixtures change would otherwise leave evidence for groups and
    /// process areas that no longer exist still queryable.
    /// </remarks>
    private static async Task<int> PushDocumentsAsync(ProvisionPlan plan)
    {
        var search = new SearchClient(new Uri(plan.Endpoint), plan.Names["index"], Credentials.Default());
        var wanted = plan.Docs.Select(d => d["citation_id"]).ToHashSet();
        var existing = new HashSet<string>();
        var options = new SearchOptions { IncludeTotalCount = false };
        options.Select.Add("citation_id");
        var results = await search.SearchAsync<SearchDocument>("*", options);
        await foreach (var result in results.Value.GetResultsAsync())
        {
            existing.Add(result.Document["citation_id"]?.ToString() ?? "");
        }

        var failed = 0;
        var stale = existing.Except(wanted).Order(StringComparer.Ordinal).ToList();
        if (stale.Count > 0)
        {
            Console.WriteLine($"    removing {stale.Count} stale document(s)");
            // Per-document failures are reported in the result, not raised.
            // Ignoring them would report a clean run while leaving evidence for
            // a group that no longer exists still queryable.
            var deleted = await search.DeleteDocumentsAsync("citation_id", stale);
            failed += deleted.Value.Results.Count(r => !r.Succeeded);
        }

        var uploaded = await search.UploadDocumentsAsync(plan.Docs);
        return failed + uploaded.Value.Results.Count(r => !r.Succeeded);
    }

    private static SearchIndexKnowledgeSource IndexKnowledgeSource(ProvisionPlan plan)
    {
        var parameters = new SearchIndexKnowledgeSourceParameters(plan.Names["index"]) { SemanticConfigurationName = SemanticConfig };
        // These take field-reference objects, not bare strings.
        foreach (var field in SourceDataFields)
        {
            parameters.SourceDataFields.Add(new SearchIndexFieldReference(field));
        }
        foreach (var field in (ReadOnlySpan<string>)["source_title", "evidence_summary"])
        {
            parameters.SearchFields.Add(new SearchIndexFieldReference(field));
        }
        return new SearchIndexKnowledgeSource(plan.Names["source"], parameters);
    }

    /// <summary>Number of non-empty path segments in a URL, as Python's urlparse splits it.</summary>
    public static int PathDepth(string address)
    {
        var rest = address;
        foreach (var separator in (ReadOnlySpan<char>)['#', '?'])
        {
            if (rest.IndexOf(separator) is var at and >= 0)
            {
                rest = rest[..at];
            }
        }
        if (rest.IndexOf("://", StringComparison.Ordinal) is var scheme and >= 0)
        {
            rest = rest[(scheme + 3)..];
            rest = rest.IndexOf('/') is var slash and >= 0 ? rest[slash..] : "";
        }
        return rest.Split('/').Count(segment => segment.Length > 0);
    }

    private static WebKnowledgeSource WebKnowledgeSource(ProvisionPlan plan)
    {
        var domains = new WebKnowledgeSourceDomains();
        foreach (var address in plan.WebDomains)
        {
            domains.AllowedDomains.Add(new WebKnowledgeSourceDomain(address)
            {
                // The service rejects include_subpages on an address more than
                // two path segments deep. A deep address is already a single
                // page, so crawl just that one.
                IncludeSubpages = PathDepth(address) <= 2,
            });
        }
        return new WebKnowledgeSource(plan.Names["web_source"]) { WebParameters = new WebKnowledgeSourceParameters { Domains = domains } };
    }

    private static AzureBlobKnowledgeSource BlobKnowledgeSource(ProvisionPlan plan) => new(
        plan.Names["blob_source"],
        // Managed-identity form: shared keys are disabled on the account.
        new AzureBlobKnowledgeSourceParameters($"ResourceId={plan.BlobResourceId};", plan.BlobContainer));

    private static KnowledgeBase KnowledgeBase(ProvisionPlan plan, List<KnowledgeSourceReference> references)
    {
        var knowledgeBase = new KnowledgeBase(plan.Names["base"], references);
        // A web source makes the base do its own reasoning, which requires a
        // model. Index-only bases do not.
        if (plan.WebDomains.Length > 0)
        {
            knowledgeBase.Models.Add(new KnowledgeBaseAzureOpenAIModel(new AzureOpenAIVectorizerParameters
            {
                ResourceUri = new Uri(plan.AoaiEndpoint),
                DeploymentName = plan.AoaiDeployment,
                ModelName = new AzureOpenAIModelName(plan.AoaiModel),
            }));
        }
        return knowledgeBase;
    }

    /// <summary>Index -> documents -> knowledge source(s) -> knowledge base.</summary>
    /// <remarks>
    /// The order is not cosmetic: a knowledge source cannot reference an index
    /// that does not exist, and a knowledge base cannot reference a source that
    /// does not exist.
    /// </remarks>
    private static async Task<int> ApplyAsync(ProvisionPlan plan)
    {
        var n = plan.Names;
        var client = new SearchIndexClient(new Uri(plan.Endpoint), Credentials.Default());

        Console.WriteLine($"1/4 index          {n["index"]}");
        await client.CreateOrUpdateIndexAsync(BuildIndex(n["index"]));

        Console.WriteLine($"2/4 documents      {plan.Docs.Count} pushed (no blob, no indexer)");
        var failed = await PushDocumentsAsync(plan);
        if (failed > 0)
        {
            Console.Error.WriteLine($"    {failed} document operation(s) failed.");
            return 1;
        }

        Console.WriteLine($"3/4 knowledge src  {n["source"]}");
        await client.CreateOrUpdateKnowledgeSourceAsync(IndexKnowledgeSource(plan));
        var references = new List<KnowledgeSourceReference> { new(n["source"]) };

        if (plan.WebDomains.Length > 0)
        {
            Console.WriteLine($"3b  web source     {n["web_source"]} -> {string.Join(", ", plan.WebDomains)}");
            await client.CreateOrUpdateKnowledgeSourceAsync(WebKnowledgeSource(plan));
            references.Add(new KnowledgeSourceReference(n["web_source"]));
        }

        if (plan.BlobContainer.Length > 0)
        {
            Console.WriteLine($"3c  blob source    {n["blob_source"]} -> {plan.BlobContainer}");
            await client.CreateOrUpdateKnowledgeSourceAsync(BlobKnowledgeSource(plan));
            references.Add(new KnowledgeSourceReference(n["blob_source"]));
        }

        Console.WriteLine($"4/4 knowledge base {n["base"]} over {references.Count} source(s)");
        await client.CreateOrUpdateKnowledgeBaseAsync(KnowledgeBase(plan, references));

        Console.WriteLine("\nDone. Point the API at it with:");
        Console.WriteLine("  EVIDENCE_SOURCE=foundry_iq");
        Console.WriteLine($"  FOUNDRY_IQ_KNOWLEDGE_BASE={n["base"]}");
        Console.WriteLine($"  FOUNDRY_IQ_KNOWLEDGE_SOURCE={n["source"]}");
        return 0;
    }

    private static async Task<int> QueryAsync(string endpoint, string suffix, string question)
    {
        var names = Names(suffix);
        var retriever = new FoundryIqEvidenceRetriever(endpoint, names["base"], names["source"]);
        var bundle = await retriever.RetrieveAsync(new EvidenceRequest("GROUP-A", "lead-response", DetectedNeedHint: question));
        Console.WriteLine($"group={bundle.DealerGroupId} citations={bundle.Citations.Count}");
        foreach (var c in bundle.Citations)
        {
            Console.WriteLine($"  [{c.CitationId}] {c.SourceTitle}");
            Console.WriteLine($"      {PyText.Head(c.EvidenceSummary, 110)}");
        }
        return bundle.Citations.Count > 0 ? 0 : 1;
    }

    /// <summary>Remove every object --apply can create, in reverse creation order.</summary>
    /// <remarks>
    /// All three knowledge sources are attempted even though a given run may
    /// only have created one: deleting the base first leaves the others
    /// unreferenced and otherwise invisible until the next name collision.
    /// </remarks>
    private static async Task<int> DeleteAsync(string endpoint, string suffix)
    {
        var n = Names(suffix);
        var client = new SearchIndexClient(new Uri(endpoint), Credentials.Default());
        var errors = 0;
        (string Label, Func<Task> Call)[] targets =
        [
            ("knowledge base", () => client.DeleteKnowledgeBaseAsync(n["base"])),
            ("index knowledge source", () => client.DeleteKnowledgeSourceAsync(n["source"])),
            ("web knowledge source", () => client.DeleteKnowledgeSourceAsync(n["web_source"])),
            ("blob knowledge source", () => client.DeleteKnowledgeSourceAsync(n["blob_source"])),
            ("index", () => client.DeleteIndexAsync(n["index"], CancellationToken.None)),
        ];
        foreach (var (label, call) in targets)
        {
            try
            {
                await call();
                Console.WriteLine($"deleted {label}");
            }
            catch (RequestFailedException exc) when (exc.Status == 404)
            {
                Console.WriteLine($"  [skip] {label}: not present");
            }
            catch (Exception exc)
            {
                // Reported, then counted.
                errors++;
                Console.Error.WriteLine($"  [fail] {label}: {exc.GetType().Name}: {exc.Message}");
            }
        }

        if (errors > 0)
        {
            Console.Error.WriteLine($"\n{errors} object(s) could not be deleted.");
            return 1;
        }
        return 0;
    }

    /// <summary>Returns null when the requested plan cannot be built as asked.</summary>
    private static async Task<ProvisionPlan?> BuildPlanAsync(string endpoint, string suffix, string webDomains, string blobContainerArg)
    {
        var blobContainer = PyText.Strip(blobContainerArg);
        var blobResourceId = blobContainer.Length > 0 ? StorageResourceId() : "";
        if (blobContainer.Length > 0 && blobResourceId.Length == 0)
        {
            // Silently dropping the blob source would provision something other
            // than what was asked for, and report success for it.
            Console.Error.WriteLine(
                $"Blob container {PyText.Repr(blobContainer)} was requested but the storage "
                + "account resource id could not be read from terraform output. Run "
                + "terraform in /infra, or pass --blob-container '' to skip the blob "
                + "source deliberately.");
            return null;
        }

        return new ProvisionPlan(
            Endpoint: endpoint,
            Suffix: suffix,
            Docs: await DocumentsAsync(),
            WebDomains: [.. webDomains.Split(',').Select(PyText.Strip).Where(d => d.Length > 0)],
            BlobContainer: blobContainer,
            BlobResourceId: blobResourceId,
            AoaiEndpoint: AoaiEndpoint(),
            AoaiDeployment: Environment.GetEnvironmentVariable("FOUNDRY_MODEL_DEPLOYMENT_EXPLAINER") is { Length: > 0 } deployment ? deployment : "asg-chat");
    }

    private static void PrintPlan(ProvisionPlan plan)
    {
        var n = plan.Names;
        Console.WriteLine($"Search endpoint : {plan.Endpoint}");
        foreach (var (label, key) in (ReadOnlySpan<(string, string)>)[("index", "index"), ("index source", "source"), ("knowledge base", "base")])
        {
            Console.WriteLine($"{label,-16}: {n[key]}");
        }
        Console.WriteLine($"{"documents",-16}: {plan.Docs.Count}");
        Console.WriteLine($"{"web allowlist",-16}: {(plan.WebDomains.Length > 0 ? string.Join(", ", plan.WebDomains) : "(disabled)")}");
        Console.WriteLine($"{"blob container",-16}: {(plan.BlobContainer.Length > 0 ? plan.BlobContainer : "(disabled)")}");
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
}
