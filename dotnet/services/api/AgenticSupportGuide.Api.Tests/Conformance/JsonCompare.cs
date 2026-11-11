using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace AgenticSupportGuide.Api.Tests.Conformance;

/// <summary>
/// Compares a recorded golden with what this track produced, by value.
/// </summary>
/// <remarks>
/// Objects compare as maps, arrays in order, numbers by value (Python writes
/// <c>72.0</c> where System.Text.Json may write <c>72</c>), and golden strings
/// after the track substitutions. Every difference is reported with its path.
/// </remarks>
public static partial class JsonCompare
{
    public static List<string> Differences(JsonNode? expected, JsonNode? actual, string path = "$")
    {
        var differences = new List<string>();
        Compare(expected, actual, path, differences);
        return differences;
    }

    private static void Compare(JsonNode? expected, JsonNode? actual, string path, List<string> differences)
    {
        switch (expected)
        {
            case null:
                if (actual is not null)
                {
                    differences.Add($"{path}: expected null, got {Show(actual)}");
                }
                return;
            case JsonObject expectedObject:
                if (actual is not JsonObject actualObject)
                {
                    differences.Add($"{path}: expected an object, got {Show(actual)}");
                    return;
                }
                foreach (var (key, value) in expectedObject)
                {
                    if (!actualObject.ContainsKey(key))
                    {
                        differences.Add($"{path}.{key}: missing");
                        continue;
                    }
                    Compare(value, actualObject[key], $"{path}.{key}", differences);
                }
                foreach (var (key, _) in actualObject)
                {
                    if (!expectedObject.ContainsKey(key))
                    {
                        differences.Add($"{path}.{key}: unexpected");
                    }
                }
                return;
            case JsonArray expectedArray:
                if (actual is not JsonArray actualArray)
                {
                    differences.Add($"{path}: expected an array, got {Show(actual)}");
                    return;
                }
                if (expectedArray.Count != actualArray.Count)
                {
                    differences.Add($"{path}: expected {expectedArray.Count} items, got {actualArray.Count}");
                }
                for (var i = 0; i < Math.Min(expectedArray.Count, actualArray.Count); i++)
                {
                    Compare(expectedArray[i], actualArray[i], $"{path}[{i}]", differences);
                }
                return;
            case JsonValue expectedValue:
                if (actual is not JsonValue actualValue)
                {
                    differences.Add($"{path}: expected {Show(expected)}, got {Show(actual)}");
                    return;
                }
                if (!ValuesEqual(expectedValue, actualValue))
                {
                    differences.Add($"{path}: expected {Show(expected)}, got {Show(actual)}");
                }
                return;
        }
    }

    private static bool ValuesEqual(JsonValue expected, JsonValue actual)
    {
        var expectedKind = expected.GetValueKind();
        var actualKind = actual.GetValueKind();
        if (expectedKind == JsonValueKind.Number && actualKind == JsonValueKind.Number)
        {
            return NumbersEqual(expected.ToJsonString(), actual.ToJsonString());
        }
        if (expectedKind == JsonValueKind.String && actualKind == JsonValueKind.String)
        {
            return Goldens.ForThisTrack(expected.GetValue<string>()) == actual.GetValue<string>();
        }
        return expectedKind == actualKind && expected.ToJsonString() == actual.ToJsonString();
    }

    // Equal by value, however each side wrote it: 72.0 equals 72.
    private static bool NumbersEqual(string expected, string actual)
    {
        if (decimal.TryParse(expected, NumberStyles.Float, CultureInfo.InvariantCulture, out var a)
            && decimal.TryParse(actual, NumberStyles.Float, CultureInfo.InvariantCulture, out var b))
        {
            return a == b;
        }
        return double.Parse(expected, NumberStyles.Float, CultureInfo.InvariantCulture) == double.Parse(actual, NumberStyles.Float, CultureInfo.InvariantCulture);
    }

    private static string Show(JsonNode? node)
    {
        var text = node?.ToJsonString() ?? "null";
        return text.Length > 160 ? text[..160] + "..." : text;
    }
}
