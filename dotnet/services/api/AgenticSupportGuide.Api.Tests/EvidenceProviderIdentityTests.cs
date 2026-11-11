using AgenticSupportGuide.Api.Evidence;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>The agent trace must name the real evidence provider.</summary>
/// <remarks>
/// The provider and model were hardcoded to "fixture"/"synthetic", so a run
/// grounded by Foundry IQ still reported fixtures. That makes the trace
/// useless for the one question it exists to answer: was this answer grounded?
/// </remarks>
public sealed class EvidenceProviderIdentityTests
{
    [Fact]
    public void Fixture_retriever_declares_itself()
    {
        var retriever = new FixtureEvidenceRetriever();
        Assert.Equal("fixture", retriever.ProviderName);
        Assert.Equal("synthetic", retriever.ProviderModel);
    }

    [Fact]
    public void Foundry_iq_retriever_declares_itself()
    {
        var retriever = new FoundryIqEvidenceRetriever(
            endpoint: "https://example.search.windows.net",
            knowledgeBase: "kb-under-test");
        Assert.Equal("foundry_iq", retriever.ProviderName);
        Assert.Equal("kb-under-test", retriever.ProviderModel);
    }

    [Fact]
    public void Both_retrievers_satisfy_the_protocol()
    {
        IEvidenceRetriever fixture = new FixtureEvidenceRetriever();
        IEvidenceRetriever foundry = new FoundryIqEvidenceRetriever(
            endpoint: "https://example.search.windows.net",
            knowledgeBase: "kb-under-test");
        Assert.NotEqual(fixture.ProviderName, foundry.ProviderName);
    }
}
