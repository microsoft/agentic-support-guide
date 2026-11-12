using System.Net;
using System.Reflection;
using System.Text;
using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Evidence;
using Azure.Core;
using Azure.Core.Pipeline;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Foundry IQ retriever: dealer group isolation and citation mapping.</summary>
/// <remarks>
/// The coordinator's whole safety story rests on evidence never crossing
/// dealer groups. With Foundry IQ that is enforced by an OData filter on a
/// filterable index field, so these tests assert the filter is actually built
/// and that the retriever still refuses anything that slips through.
///
/// The Python tests replace the retriever's private <c>_retrieve_sync</c>. This
/// retriever builds a new Search client for every call, so the fake stands in
/// for the search service instead, installed where each new Azure SDK client
/// takes its HTTP transport from: <see cref="ClientOptions.Default"/>. Every
/// test puts the original transport back. Nothing reaches the network.
/// </remarks>
public sealed class FoundryIqTests : IDisposable
{
    private const string Endpoint = "https://example.search.windows.net";

    // ClientOptions.Default is process-wide, so each test restores what it found.
    private readonly HttpPipelineTransport _originalTransport = ClientOptions.Default.Transport;

    public void Dispose() => ClientOptions.Default.Transport = _originalTransport;

    private static Dictionary<string, string> Doc(string citationId, string group) => new()
    {
        ["citation_id"] = citationId,
        ["dealer_group_id"] = group,
        ["source_title"] = "Group A - Enquiry Response Benchmarks",
        ["evidence_summary"] = "Synthetic benchmark guidance.",
        ["source_type"] = "structured_data",
        ["section_or_page"] = "section 1",
        ["source_ref"] = "fixture://group-a/lr-01",
    };

    private static FoundryIqEvidenceRetriever Retriever(List<Dictionary<string, string>> documents, Dictionary<string, string> captured)
    {
        var retriever = new FoundryIqEvidenceRetriever(
            endpoint: Endpoint,
            knowledgeBase: "asg-kb-demo",
            credentialFactory: () => new StaticCredential());

        List<Dictionary<string, string>> FakeSearch(JsonNode request)
        {
            // The dealer group reaches the service only inside the filter.
            captured["filter_add_on"] = request["knowledgeSourceParams"]![0]!["filterAddOn"]!.GetValue<string>();
            return documents;
        }

        UseSearchService(FakeSearch);
        return retriever;
    }

    // Every Search client created after this sends its requests to `search`.
    private static void UseSearchService(Func<JsonNode, List<Dictionary<string, string>>> search) =>
        ClientOptions.Default.Transport = new HttpClientTransport(new SearchService(search));

    // The retriever's private members, reached by reflection, as the Python
    // tests import the module's private functions and read its attribute.
    private static Citation? ToCitation(Dictionary<string, string> doc, string dealerGroupId) =>
        (Citation?)typeof(FoundryIqEvidenceRetriever)
            .GetMethod("ToCitation", BindingFlags.NonPublic | BindingFlags.Static)!
            .Invoke(null, [doc, dealerGroupId]);

    private static string EscapeOData(string value) =>
        (string)typeof(FoundryIqEvidenceRetriever)
            .GetMethod("EscapeOData", BindingFlags.NonPublic | BindingFlags.Static)!
            .Invoke(null, [value])!;

    private static string KnowledgeSourceOf(FoundryIqEvidenceRetriever retriever) =>
        (string)typeof(FoundryIqEvidenceRetriever)
            .GetField("_knowledgeSource", BindingFlags.NonPublic | BindingFlags.Instance)!
            .GetValue(retriever)!;

    [Fact]
    public async Task Missing_dealer_group_is_refused_before_any_call()
    {
        var retriever = Retriever([], []);
        await Assert.ThrowsAnyAsync<EvidenceRetrievalException>(() =>
            retriever.RetrieveAsync(
                new EvidenceRequest(DealerGroupId: "", Category: "lead-response", DetectedNeedHint: ""),
                TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Citations_are_mapped_from_index_documents()
    {
        var retriever = Retriever([Doc("GROUP-A-el-01", "GROUP-A")], []);
        var bundle = await retriever.RetrieveAsync(
            new EvidenceRequest(DealerGroupId: "GROUP-A", Category: "lead-response", DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.Equal("GROUP-A", bundle.DealerGroupId);
        Assert.Equal(["GROUP-A-el-01"], bundle.Citations.Select(c => c.CitationId));
    }

    /// <summary>Defence in depth.</summary>
    /// <remarks>
    /// The OData filter should make this impossible, but blob and web knowledge
    /// sources carry no dealer group field, so anything that reaches the retriever
    /// from another dealer group must still be discarded here.
    /// </remarks>
    [Fact]
    public async Task Foreign_dealer_group_documents_are_dropped()
    {
        var retriever = Retriever([Doc("GROUP-A-el-01", "GROUP-A"), Doc("GROUP-B-el-01", "GROUP-B")], []);
        var bundle = await retriever.RetrieveAsync(
            new EvidenceRequest(DealerGroupId: "GROUP-A", Category: "lead-response", DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.Equal(["GROUP-A-el-01"], bundle.Citations.Select(c => c.CitationId));
        Assert.True(bundle.Citations.All(c => c.DealerGroupId == "GROUP-A"));
    }

    [Fact]
    public async Task Documents_without_a_citation_id_are_dropped()
    {
        var retriever = Retriever([new() { ["dealer_group_id"] = "GROUP-A", ["source_title"] = "No id" }], []);
        var bundle = await retriever.RetrieveAsync(
            new EvidenceRequest(DealerGroupId: "GROUP-A", Category: "lead-response", DetectedNeedHint: ""),
            TestContext.Current.CancellationToken);
        Assert.Empty(bundle.Citations);
    }

    [Fact]
    public async Task Provider_failure_becomes_a_typed_evidence_error()
    {
        var retriever = new FoundryIqEvidenceRetriever(
            endpoint: Endpoint,
            knowledgeBase: "kb",
            credentialFactory: () => new StaticCredential());

        static List<Dictionary<string, string>> Boom(JsonNode request) =>
            throw new InvalidOperationException("search exploded");

        UseSearchService(Boom);
        var exception = await Assert.ThrowsAnyAsync<EvidenceRetrievalException>(() =>
            retriever.RetrieveAsync(
                new EvidenceRequest(DealerGroupId: "GROUP-A", Category: "x", DetectedNeedHint: ""),
                TestContext.Current.CancellationToken));
        // The raw provider message must not reach the caller.
        Assert.DoesNotContain("search exploded", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Unconfigured_retriever_fails_fast()
    {
        Assert.ThrowsAny<EvidenceRetrievalException>(() => new FoundryIqEvidenceRetriever(endpoint: "", knowledgeBase: ""));
    }

    [Theory]
    [InlineData("asg-kb-demo", "asg-ks-demo")]
    // The portal walkthrough produces this name. A plain
    // .Replace("-kb-", "-ks-") no-ops here, leaving the retriever querying
    // a source that does not exist.
    [InlineData("kb-alias", "ks-alias")]
    [InlineData("team-kb", "team-ks")]
    public void Source_name_derived_from_knowledge_base(string knowledgeBase, string expected)
    {
        Assert.Equal(expected, FoundryIqEvidenceRetriever.DeriveSourceName(knowledgeBase));
    }

    [Fact]
    public void Explicit_knowledge_source_wins_over_derivation()
    {
        var retriever = new FoundryIqEvidenceRetriever(
            endpoint: "https://example.search.windows.net",
            knowledgeBase: "kb-alias",
            knowledgeSource: "totally-different-source");
        Assert.Equal("totally-different-source", KnowledgeSourceOf(retriever));
    }

    [Fact]
    public void Unknown_source_type_falls_back_rather_than_crashing()
    {
        var citation = ToCitation(
            new Dictionary<string, string>
            {
                ["citation_id"] = "X",
                ["dealer_group_id"] = "GROUP-A",
                ["source_type"] = "not-a-real-type",
                ["evidence_summary"] = "text",
            },
            "GROUP-A");
        Assert.NotNull(citation);
        Assert.Equal("GROUP-A", citation.DealerGroupId);
    }

    /// <summary>The live failure this guards against.</summary>
    /// <remarks>
    /// A knowledge base holds blob and web sources next to the index, and those
    /// carry no dealer_group_id. Verified against a live knowledge base: scoping the
    /// request to the index source does NOT stop the blob source contributing.
    /// <c>ToCitation</c> previously defaulted the dealer group to the caller's, turning
    /// unscoped content into an apparently dealer group-owned citation that passed
    /// every downstream isolation check.
    /// </remarks>
    [Fact]
    public void Untagged_documents_are_dropped_not_relabelled()
    {
        var untagged = new Dictionary<string, string>
        {
            ["citation_id"] = "BLOB-1",
            ["evidence_summary"] = "Text from a blob document with no dealer group field.",
        };
        Assert.Null(ToCitation(untagged, "GROUP-A"));
    }

    [Fact]
    public void To_citation_drops_foreign_dealer_group_documents()
    {
        var foreign = new Dictionary<string, string>
        {
            ["citation_id"] = "B-1",
            ["dealer_group_id"] = "GROUP-B",
            ["evidence_summary"] = "Evidence belonging to another dealer group.",
        };
        Assert.Null(ToCitation(foreign, "GROUP-A"));
    }

    /// <summary>A document missing required text must not abort the whole retrieval.</summary>
    [Fact]
    public void Partial_documents_are_dropped_not_raised()
    {
        Assert.Null(ToCitation(new Dictionary<string, string> { ["citation_id"] = "X", ["dealer_group_id"] = "GROUP-A" }, "GROUP-A"));
    }

    /// <summary>An unescaped quote would break the filter, silently widening the scope.</summary>
    [Theory]
    [InlineData("GROUP-A", "dealer_group_id eq 'GROUP-A'")]
    [InlineData("O'Neil", "dealer_group_id eq 'O''Neil'")]
    public void Odata_filter_escapes_quotes(string group, string expected)
    {
        Assert.Equal(expected, $"dealer_group_id eq '{EscapeOData(group)}'");
    }

    /// <summary>
    /// The knowledge base's retrieve endpoint. <c>search</c> turns the request
    /// into the documents it answers with, each returned as a search index
    /// reference whose source data is the document.
    /// </summary>
    private sealed class SearchService(Func<JsonNode, List<Dictionary<string, string>>> search) : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var payload = JsonNode.Parse(request.Content is null ? "{}" : await request.Content.ReadAsStringAsync(cancellationToken))!;
            var references = new JsonArray();
            foreach (var document in search(payload))
            {
                var index = references.Count;
                references.Add(new JsonObject
                {
                    ["type"] = "searchIndex",
                    ["id"] = $"{index}",
                    ["activitySource"] = 1,
                    ["docKey"] = $"doc-{index}",
                    ["sourceData"] = new JsonObject(document.Select(field => KeyValuePair.Create(field.Key, (JsonNode?)field.Value))),
                });
            }
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject { ["references"] = references }.ToJsonString(), Encoding.UTF8, "application/json"),
            };
        }
    }

    // The retriever authenticates every call; a fixed token keeps that local.
    private sealed class StaticCredential : TokenCredential
    {
        public override AccessToken GetToken(TokenRequestContext requestContext, CancellationToken cancellationToken) =>
            new("test-token", DateTimeOffset.UtcNow.AddHours(1));

        public override ValueTask<AccessToken> GetTokenAsync(TokenRequestContext requestContext, CancellationToken cancellationToken) =>
            ValueTask.FromResult(GetToken(requestContext, cancellationToken));
    }
}
