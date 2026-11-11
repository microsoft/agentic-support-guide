using System.Text.Json;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Parity;
using Azure.Core;
using Azure.Identity;
using Azure.Search.Documents.KnowledgeBases;
using Azure.Search.Documents.KnowledgeBases.Models;

namespace AgenticSupportGuide.Api.Evidence;

/// <summary>
/// Foundry IQ implementation of <see cref="IEvidenceRetriever"/>.
/// </summary>
/// <remarks>
/// This is what makes the running app stop serving in-memory fixtures. The
/// workflow does not know or care which retriever it holds - the interface is
/// the seam.
///
/// Dealer group isolation is enforced by an OData filter on a
/// <c>filterable</c> index field, not by asking a model nicely. A cross-group
/// citation is impossible here, not merely discouraged.
/// </remarks>
public sealed class FoundryIqEvidenceRetriever : IEvidenceRetriever
{
    // Agentic retrieval costs latency; keep it modest for an interactive demo.
    public const int MaxRuntimeSeconds = 30;
    public const double RerankerThreshold = 1.5;

    private readonly string _endpoint;
    private readonly string _knowledgeBase;
    private readonly string _knowledgeSource;
    private readonly Func<TokenCredential> _credentialFactory;

    public FoundryIqEvidenceRetriever(string endpoint, string knowledgeBase, string knowledgeSource = "", Func<TokenCredential>? credentialFactory = null)
    {
        if (string.IsNullOrEmpty(endpoint) || string.IsNullOrEmpty(knowledgeBase))
        {
            throw new EvidenceRetrievalException("FOUNDRY_IQ_NOT_CONFIGURED", "AZURE_SEARCH_ENDPOINT and FOUNDRY_IQ_KNOWLEDGE_BASE must be set.");
        }
        _endpoint = endpoint;
        _knowledgeBase = knowledgeBase;
        // Prefer an explicit source name. The fallback rewrites a `kb` segment so
        // a portal-created `kb-alias` still resolves to `ks-alias`; a plain
        // replace of "-kb-" silently no-ops on that name and leaves the
        // retriever querying a source that does not exist.
        _knowledgeSource = knowledgeSource.Length > 0 ? knowledgeSource : DeriveSourceName(knowledgeBase);
        _credentialFactory = credentialFactory ?? (() => new DefaultAzureCredential());
    }

    public string ProviderName => "foundry_iq";

    public string ProviderModel => _knowledgeBase;

    // HasDealerGroup cannot prove anything about a remote knowledge base without
    // a network call, so readiness must not be reported as verified.
    public bool EvidenceVerifiable => false;

    /// <summary>
    /// Map a knowledge base name to its conventional knowledge source name.
    /// </summary>
    /// <remarks>
    /// Handles <c>asg-kb-demo</c> -> <c>asg-ks-demo</c> and a portal-created
    /// <c>kb-demo</c> -> <c>ks-demo</c>. Anchoring on a <c>kb</c> segment
    /// rather than the substring <c>-kb-</c> is what makes the second case work.
    /// </remarks>
    public static string DeriveSourceName(string knowledgeBase) =>
        Regex.Replace(knowledgeBase, "(^|-)kb(-|$)", "$1ks$2", RegexOptions.CultureInvariant);

    // Local check only. This retriever talks to a remote service, so it cannot
    // answer "is there evidence" without network I/O, and /api/health/details
    // is polled on every page load. Reporting True here would make readiness
    // green with a deleted knowledge base, so callers must treat it as
    // "configured", not "verified".
    public bool HasDealerGroup(string dealerGroupId) => !string.IsNullOrEmpty(dealerGroupId);

    public async Task<EvidenceBundle> RetrieveAsync(EvidenceRequest request, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(request.DealerGroupId))
        {
            throw new EvidenceRetrievalException("MISSING_DEALER_GROUP_ID", "Evidence request is missing a dealer_group_id.");
        }

        List<IDictionary<string, string>> documents;
        try
        {
            documents = await RetrieveDocumentsAsync(request, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            // Mapped to a safe error: the SDK's message can carry document text.
            throw new EvidenceRetrievalException("FOUNDRY_IQ_UNAVAILABLE", "Foundry IQ retrieval failed.");
        }

        var citations = documents
            .Select(doc => ToCitation(doc, request.DealerGroupId))
            // Defence in depth: the filter should make this impossible.
            .Where(c => c is not null && c.DealerGroupId == request.DealerGroupId)
            .Select(c => c!)
            .ToList();
        return new EvidenceBundle(request.DealerGroupId, citations);
    }

    private async Task<List<IDictionary<string, string>>> RetrieveDocumentsAsync(EvidenceRequest request, CancellationToken cancellationToken)
    {
        var client = new KnowledgeBaseRetrievalClient(new Uri(_endpoint), _knowledgeBase, _credentialFactory());
        var query = request.DetectedNeedHint.Length > 0 ? request.DetectedNeedHint : request.Category;
        var payload = new KnowledgeBaseRetrievalRequest
        {
            MaxRuntimeInSeconds = MaxRuntimeSeconds,
            IncludeActivity = false,
        };
        payload.Intents.Add(new KnowledgeRetrievalSemanticIntent(query));
        payload.KnowledgeSourceParams.Add(new SearchIndexKnowledgeSourceParams(_knowledgeSource)
        {
            IncludeReferences = true,
            IncludeReferenceSourceData = true,
            // The demo corpus is a handful of short documents per group, so the
            // service default threshold discards valid matches.
            RerankerThreshold = (float)RerankerThreshold,
            // Engine-enforced dealer group isolation.
            FilterAddOn = $"dealer_group_id eq '{EscapeOData(request.DealerGroupId)}'",
        });
        var response = await client.RetrieveAsync(payload, cancellationToken);
        return FlattenReferences(response.Value);
    }

    /// <summary>Single quotes are the only OData string escape that matters here.</summary>
    private static string EscapeOData(string value) => value.Replace("'", "''", StringComparison.Ordinal);

    /// <summary>Pull source documents out of the response's references.</summary>
    private static List<IDictionary<string, string>> FlattenReferences(KnowledgeBaseRetrievalResponse response)
    {
        var output = new List<IDictionary<string, string>>();
        foreach (var reference in response.References ?? [])
        {
            if (reference.SourceData is not { Count: > 0 } data)
            {
                continue;
            }
            output.Add(data.ToDictionary(kv => kv.Key, kv => AsText(kv.Value)));
        }
        return output;
    }

    // A source-data value is JSON; a string field is read as its text, as
    // Python's str() of the decoded value would be.
    private static string AsText(BinaryData? value)
    {
        if (value is null)
        {
            return "";
        }
        try
        {
            using var document = JsonDocument.Parse(value);
            return document.RootElement.ValueKind switch
            {
                JsonValueKind.String => document.RootElement.GetString() ?? "",
                JsonValueKind.Null => "",
                _ => document.RootElement.GetRawText(),
            };
        }
        catch (JsonException)
        {
            return value.ToString();
        }
    }

    private static Citation? ToCitation(IDictionary<string, string> doc, string dealerGroupId)
    {
        string Field(string name) => doc.TryGetValue(name, out var v) ? v : "";

        var citationId = PyText.Strip(Field("citation_id"));
        var summary = PyText.Strip(Field("evidence_summary"));
        // Citation enforces non-empty fields. A partial document is dropped
        // rather than allowed to fail retrieval midway.
        if (citationId.Length == 0 || summary.Length == 0)
        {
            return null;
        }
        // A knowledge base can hold blob and web sources alongside the index, and
        // those carry no dealer_group_id. Scoping the request to the index source
        // does NOT stop them contributing - verified against a live knowledge
        // base. Defaulting to the caller's group here would relabel unscoped
        // content as theirs, which is exactly the cross-group citation this class
        // claims to make impossible. Ownership must be proven, not assumed.
        var docGroup = PyText.Strip(Field("dealer_group_id"));
        if (docGroup != dealerGroupId)
        {
            return null;
        }
        var rawType = PyText.Strip(Field("source_type"));
        var sourceType = CitationSourceType.All.Contains(rawType) ? rawType : CitationSourceType.StructuredData;
        var citation = new Citation(
            CitationId: citationId,
            DealerGroupId: docGroup,
            SourceType: sourceType,
            SourceTitle: Or(Field("source_title"), "Untitled source"),
            SectionOrPage: Or(Field("section_or_page"), "section 1"),
            EvidenceSummary: summary,
            SourceRef: Or(Field("source_ref"), $"foundry-iq://{citationId}"),
            RetrievedAt: Audit.UtcNowIso(),
            Confidence: 0.8);
        // An over-long field is as unusable as a missing one. Drop the document.
        return citation.IsValid() ? citation : null;
    }

    private static string Or(string value, string fallback) => value.Length > 0 ? value : fallback;
}
