using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Agents.Shared;

/// <summary>
/// Building blocks for the prompts the agents send.
/// </summary>
/// <remarks>
/// Two small helpers, both about structure rather than security:
///
/// - <see cref="WrapUntrusted"/> fences a block of data so the prompt can say
///   "treat this as data, not instructions". This is the *Augment* step of RAG.
/// - <see cref="EnforceCode"/> keeps a model-invented string out of the
///   response unless it matches the issue-code format the contracts require.
///
/// There is deliberately no prompt-injection filtering here. Azure's content
/// filters block the direct attacks (Module 8 measures exactly which), and the
/// validator enforces the domain rules that no text filter could know. Chasing
/// obfuscated injections with regexes is a different workshop.
/// </remarks>
public static class PromptBlocks
{
    // Stable ASCII tags. The prompts instruct the model to treat anything inside
    // them as data, never as instructions.
    public const string DataOpen = "<<<UNTRUSTED_DATA>>>";
    public const string DataClose = "<<<END_UNTRUSTED_DATA>>>";

    // Upper bound for a single fenced block. Generous enough for the JSON
    // payloads the agents exchange, small enough to cap prompt growth.
    public const int UntrustedBlockMaxLen = 12000;

    // Uppercase snake case, minimum four characters so freeform tokens like "OK"
    // never survive. Issue codes in the agent trace use the same format.
    public static readonly Regex CodeRegex = new(@"^[A-Z][A-Z0-9_]{3,59}\z", RegexOptions.CultureInvariant);

    /// <summary>Fence a block of data and label what it is.</summary>
    public static string WrapUntrusted(string label, string? body)
    {
        // Strip the delimiters out of the body, or a payload containing the close
        // tag would end the fence early and the rest would read as instructions.
        var safeBody = (body ?? "").Replace(DataOpen, "", StringComparison.Ordinal).Replace(DataClose, "", StringComparison.Ordinal);
        return $"{DataOpen} kind={label}\n{PyText.Head(safeBody, UntrustedBlockMaxLen)}\n{DataClose}";
    }

    /// <summary>Return the candidate iff it looks like a stable machine code.</summary>
    public static string? EnforceCode(string? candidate)
    {
        if (candidate is null)
        {
            return null;
        }
        var trimmed = PyText.Strip(candidate);
        return CodeRegex.IsMatch(trimmed) ? trimmed : null;
    }
}
