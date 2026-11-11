using AgenticSupportGuide.Api.Agents.Shared;

namespace AgenticSupportGuide.Api.Evidence;

/// <summary>Base class for retrieval failures. Only carries safe codes.</summary>
public class EvidenceRetrievalException(string code, string safeMessage) : Exception($"{code}: {safeMessage}")
{
    public string Code { get; } = code;

    public string SafeMessage { get; } = safeMessage;
}

/// <summary>Retriever returned a citation whose group does not match the request.</summary>
public sealed class CrossDealerGroupEvidenceException(string code, string safeMessage) : EvidenceRetrievalException(code, safeMessage);

/// <summary>
/// Dealer-group-scoped retrieval request.
/// </summary>
/// <remarks>
/// <c>DealerGroupId</c> is mandatory. A retriever MUST NOT return citations
/// from other groups even if the caller misroutes the request.
/// </remarks>
public sealed record EvidenceRequest(string DealerGroupId, string Category, string DetectedNeedHint, int MaxItems = 6);

/// <summary>Return type for a retrieval call. <c>Citations</c> is group-scoped.</summary>
public sealed record EvidenceBundle(string DealerGroupId, IReadOnlyList<Citation> Citations)
{
    public bool IsEmpty() => Citations.Count == 0;
}

/// <summary>
/// Dealer-group-scoped evidence retrieval: the stable interface the workflow uses.
/// </summary>
/// <remarks>
/// Production ambition: resolve evidence from per-group Microsoft Fabric
/// workspaces/lakehouses, group-approved documents, resource libraries, and
/// policy documents (potentially via Foundry IQ or Fabric IQ grounding).
///
/// Every retrieval call is required to carry a <c>dealer_group_id</c>; a
/// retriever refuses to return citations tagged with a different group than
/// the request. Retrieval is asynchronous because real implementations do
/// network I/O; the fixture retriever is in-memory but keeps the same
/// signature so a Foundry IQ or Fabric retriever can be swapped in without
/// touching the workflow or the agents.
/// </remarks>
public interface IEvidenceRetriever
{
    /// <summary>
    /// Shown in the agent trace so a reader can tell grounded answers from
    /// fixture answers. Hardcoding this made the trace claim "fixture" even
    /// when Foundry IQ served the evidence.
    /// </summary>
    string ProviderName { get; }

    /// <summary>What actually produced the evidence: "synthetic" for fixtures, the knowledge base name for Foundry IQ.</summary>
    string ProviderModel { get; }

    /// <summary>
    /// True when <see cref="HasDealerGroup"/> is authoritative. Fixtures hold
    /// their data in memory and can answer honestly. A remote retriever cannot,
    /// without network I/O on an endpoint the UI polls on every page load, so it
    /// must not be treated as proof that evidence exists.
    /// </summary>
    bool EvidenceVerifiable { get; }

    /// <summary>
    /// Return a dealer-group-scoped evidence bundle. Throws
    /// <see cref="EvidenceRetrievalException"/> on failure. Must not return
    /// citations tagged with a different group than the request.
    /// </summary>
    Task<EvidenceBundle> RetrieveAsync(EvidenceRequest request, CancellationToken cancellationToken = default);

    /// <summary>True if the retriever has any evidence for this group.</summary>
    bool HasDealerGroup(string dealerGroupId);
}
