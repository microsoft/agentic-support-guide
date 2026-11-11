using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Tests.Conformance;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>The comparison the conformance tests rest on must itself notice a difference.</summary>
public class JsonCompareTests
{
    [Fact]
    public void Numbers_compare_by_value() =>
        Assert.Empty(JsonCompare.Differences(JsonNode.Parse("{\"a\": 72.0}"), JsonNode.Parse("{\"a\": 72}")));

    [Fact]
    public void A_changed_number_is_reported() =>
        Assert.Single(JsonCompare.Differences(JsonNode.Parse("{\"a\": 72.5}"), JsonNode.Parse("{\"a\": 72.4}")));

    [Fact]
    public void A_missing_or_extra_key_is_reported() =>
        Assert.Equal(2, JsonCompare.Differences(JsonNode.Parse("{\"a\": 1}"), JsonNode.Parse("{\"b\": 1}")).Count);

    [Fact]
    public void Array_order_matters() =>
        Assert.NotEmpty(JsonCompare.Differences(JsonNode.Parse("[1, 2]"), JsonNode.Parse("[2, 1]")));

    [Fact]
    public void Golden_strings_are_read_with_this_tracks_paths() =>
        Assert.Empty(JsonCompare.Differences(
            JsonValue.Create("Run python/scripts/validate_agent_definitions.py."),
            JsonValue.Create("Run dotnet/scripts/validate_agent_definitions.cs.")));
}
