using System.Text.Json;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Parity;
using AgenticSupportGuide.Api.Workflows;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>Issue codes must be a bounded vocabulary, never exception text.</summary>
/// <remarks>
/// <c>code = str(exc)</c> put raw parse-failure text into the trace. Pydantic quotes
/// the offending value, and that value is model output derived from a
/// dealer group's evidence. Issue codes travel to the API response and to
/// Application Insights, so anything free-form there is an exfiltration path.
/// </remarks>
public sealed class IssueCodesTests
{
    // The .NET schema failure, built to quote the value as Pydantic's error for `_Tiny(value=secret)` does.
    private static ContractValidationException ValidationErrorQuoting(string secret) => new(secret);

    [Fact]
    public void Decode_failures_get_a_fixed_code()
    {
        try
        {
            JsonDocument.Parse("{not json").Dispose();
        }
        catch (JsonException exc)
        {
            Assert.Equal("AGENT_INVALID_JSON_NOT_JSON", Failures.InvalidJsonCode(exc));
        }
    }

    [Fact]
    public void Schema_failures_get_a_fixed_code()
    {
        var exc = ValidationErrorQuoting("abc");
        Assert.Equal("AGENT_INVALID_JSON_SCHEMA_MISMATCH", Failures.InvalidJsonCode(exc));
    }

    /// <summary>Issue codes are uppercase snake case; colons are not allowed.</summary>
    /// <remarks>
    /// An earlier version emitted <c>AGENT_INVALID_JSON:NOT_JSON</c>, which broke the
    /// very format it was describing.
    /// </remarks>
    [Fact]
    public void Every_issue_code_satisfies_the_code_format()
    {
        string[] codes =
        [
            Failures.InvalidJsonCode(new JsonException("x")),
            Failures.InvalidJsonCode(ValidationErrorQuoting("abc")),
            Failures.InvalidJsonCode(new ArgumentException("anything")),
        ];
        foreach (var code in codes)
        {
            Assert.True(PromptBlocks.CodeRegex.IsMatch(code), $"{PyText.Repr(code)} violates {PyText.Repr(PromptBlocks.CodeRegex.ToString())}");
        }
    }

    [Fact]
    public void Issue_code_never_contains_the_offending_value()
    {
        var secret = "LEARNER-PRIVATE-VALUE-42";
        var exc = ValidationErrorQuoting(secret);
        Assert.True(exc.Message.Contains(secret, StringComparison.Ordinal), "precondition: the validation error quotes the bad value");
        Assert.DoesNotContain(secret, Failures.InvalidJsonCode(exc), StringComparison.Ordinal);
    }

    // Python's ValueError and RuntimeError.
    public static TheoryData<Exception> UnknownFailures() =>
    [
        new ArgumentException("boom with detail"),
        new InvalidOperationException("also detail"),
    ];

    [Theory]
    [MemberData(nameof(UnknownFailures))]
    public void Unknown_failures_fall_back_to_a_fixed_code(Exception exc)
    {
        var code = Failures.InvalidJsonCode(exc);
        Assert.Equal("AGENT_INVALID_JSON_UNPARSEABLE", code);
        Assert.DoesNotContain("detail", code, StringComparison.Ordinal);
    }
}
