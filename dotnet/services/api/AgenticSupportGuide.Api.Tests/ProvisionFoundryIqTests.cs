namespace AgenticSupportGuide.Api.Tests;

/// <summary>The web knowledge source encodes a service constraint that is easy to miss.</summary>
/// <remarks>
/// Azure AI Search rejects <c>include_subpages=true</c> on an address more
/// than two path segments deep. Module 6 hands learners a four-segment
/// census.gov URL, so hardcoding the flag made the documented command fail
/// outright.
/// </remarks>
public class ProvisionFoundryIqTests
{
    [Theory]
    [InlineData("https://www.census.gov", 0)]
    [InlineData("https://www.census.gov/econ", 1)]
    [InlineData("https://www.census.gov/econ/indviz", 2)]
    [InlineData("https://www.census.gov/econ/indviz/auto/main.html", 4)]
    [InlineData("https://www.census.gov/econ/", 1)]
    public void Path_depth_counts_segments(string address, int depth)
    {
        Assert.Equal(depth, ProvisionFoundryIq.PathDepth(address));
    }

    [Fact]
    public void The_documented_census_url_is_too_deep_for_subpages()
    {
        // The URL in Module 6 must resolve to include_subpages=false.
        Assert.True(ProvisionFoundryIq.PathDepth("https://www.census.gov/econ/indviz/auto/main.html") > 2);
    }
}
