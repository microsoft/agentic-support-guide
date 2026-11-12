using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Parity;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace AgenticSupportGuide.Hosted;

/// <summary>
/// Input and output safety for the hosted agent.
/// </summary>
/// <remarks>
/// Separate from Program.cs so it can be unit-tested without booting the
/// Responses server.
///
/// This exists because the hosted agent runs standalone: it never reaches the
/// API's coordinator or validator agent, so it has to enforce the domain rule
/// itself. <see cref="Around"/> is Agent Framework agent middleware, so it
/// applies to every call the host makes, streamed or not.
/// </remarks>
public static partial class SafetyGate
{
    // The endpoint is internet-reachable, so it bounds its own input.
    public const int QuestionMaxLen = 2000;

    // Hard ceiling on what is collected before the cap above is applied.
    // Generous next to a real question, small next to a crafted payload.
    private const int CollectMaxChars = 200_000;

    public const string EmptyQuestionReply = "Ask a question about dealership support practice.";

    public const string HumanReviewCaveat = Determinations.HumanReviewCaveat;

    private static readonly string[] AnswerKeys = ["answer", "text", "response"];

    /// <summary>Join the request's text, bounded before it is normalised.</summary>
    /// <remarks>
    /// Collection stops once the ceiling is passed, so a request with many
    /// content blocks cannot make this endpoint normalise megabytes it was
    /// always going to throw away.
    /// </remarks>
    public static string BoundedQuestion(IEnumerable<string?> texts)
    {
        var collected = new List<string>();
        var total = 0;
        foreach (var text in texts)
        {
            if (string.IsNullOrEmpty(text))
            {
                continue;
            }
            collected.Add(text);
            total += PyText.Len(text);
            if (total > CollectMaxChars)
            {
                break;
            }
        }
        return PyText.Head(PyText.Strip(PyText.Head(string.Join("\n", collected), CollectMaxChars)), QuestionMaxLen);
    }

    /// <summary>Unwrap a fenced JSON payload so a caveat is not appended to JSON.</summary>
    /// <remarks>
    /// This agent's contract is plain language, but models often over-format
    /// into ```json {"answer": ...}```. Appending prose to that would produce
    /// something neither a human nor a parser can use.
    /// </remarks>
    public static string PlainText(string answer)
    {
        var stripped = PyText.Strip(answer);
        if (Fence().Match(stripped) is { Success: true } fence)
        {
            stripped = PyText.Strip(fence.Groups[1].Value);
        }
        if (stripped.StartsWith('{'))
        {
            if (!TryParsePythonJson(stripped, out var payload))
            {
                return answer;
            }
            if (payload.ValueKind == JsonValueKind.Object)
            {
                foreach (var key in AnswerKeys)
                {
                    if (LastValue(payload, key) is { ValueKind: JsonValueKind.String } value
                        && PyText.Strip(value.GetString()!) is { Length: > 0 } text)
                    {
                        return text;
                    }
                }
            }
        }
        return answer;
    }

    /// <summary>Deterministic output check, because no validator agent runs here.</summary>
    public static string Gate(string answer)
    {
        var text = PlainText(answer);
        if (Determinations.AssertsDetermination(text) || Determinations.DeniesHumanReview(text))
        {
            return "That response was withheld because it read as a determination "
                + "this system must never make. " + HumanReviewCaveat;
        }
        // Matching the caveat itself, not the words "human review", because
        // "No human review is needed." satisfied the looser check and was then
        // returned untouched — with the caveat suppressed.
        if (text.Contains(HumanReviewCaveat, StringComparison.Ordinal))
        {
            return text;
        }
        return $"{text}\n\n{HumanReviewCaveat}";
    }

    /// <summary>Decides what reaches the model, and what comes back from it.</summary>
    /// <remarks>
    /// In: only this request's text, bounded and fenced as untrusted data. No
    /// session, so nothing from an earlier turn reaches the model, and no caller
    /// options, so a caller cannot swap the model, the instructions or the tools.
    /// Out: the deterministic gate over the whole answer. A streamed answer is
    /// held until it is complete, because a gate that sees half an answer
    /// cannot withhold the other half.
    /// </remarks>
    public static AIAgent Around(AIAgent agent) => agent.AsBuilder().Use(RunAsync, RunStreamingAsync).Build();

    private static async Task<AgentResponse> RunAsync(
        IEnumerable<ChatMessage> messages, AgentSession? session, AgentRunOptions? options, AIAgent innerAgent, CancellationToken cancellationToken)
    {
        var question = BoundedQuestion(messages.Select(MessageText));
        if (question.Length == 0)
        {
            // A fixed reply, and no model call.
            return new AgentResponse(new ChatMessage(ChatRole.Assistant, EmptyQuestionReply));
        }
        var response = await innerAgent.RunAsync(Fenced(question), session: null, options: null, cancellationToken);
        return Gated(response);
    }

    private static async IAsyncEnumerable<AgentResponseUpdate> RunStreamingAsync(
        IEnumerable<ChatMessage> messages, AgentSession? session, AgentRunOptions? options, AIAgent innerAgent, [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        var question = BoundedQuestion(messages.Select(MessageText));
        if (question.Length == 0)
        {
            yield return new AgentResponseUpdate(ChatRole.Assistant, EmptyQuestionReply);
            yield break;
        }
        var updates = new List<AgentResponseUpdate>();
        await foreach (var update in innerAgent.RunStreamingAsync(Fenced(question), session: null, options: null, cancellationToken))
        {
            updates.Add(update);
        }
        foreach (var update in Gated(updates.ToAgentResponse()).ToAgentResponseUpdates())
        {
            yield return update;
        }
    }

    private static ChatMessage[] Fenced(string question) =>
        [new ChatMessage(ChatRole.User, PromptBlocks.WrapUntrusted("user question", question))];

    private static AgentResponse Gated(AgentResponse response) =>
        new(new ChatMessage(ChatRole.Assistant, Gate(ResponseText(response))))
        {
            ResponseId = response.ResponseId,
            CreatedAt = response.CreatedAt,
            FinishReason = response.FinishReason,
            Usage = response.Usage,
        };

    // Agent Framework's Python Message.text joins a message's text parts with
    // a space, and a response's messages with nothing; spelled out so both
    // tracks gate the same text.
    private static string MessageText(ChatMessage message) =>
        string.Join(" ", message.Contents.OfType<TextContent>().Select(content => content.Text));

    private static string ResponseText(AgentResponse response) => string.Concat(response.Messages.Select(MessageText));

    // A repeated key: the last one wins, as in a Python dict.
    private static JsonElement? LastValue(JsonElement payload, string key)
    {
        JsonElement? found = null;
        foreach (var property in payload.EnumerateObject())
        {
            if (property.NameEquals(key))
            {
                found = property.Value;
            }
        }
        return found;
    }

    /// <summary>What Python's <c>json.loads</c> would read, or false where it would raise.</summary>
    /// <remarks>
    /// Python also reads the bare NaN, Infinity and -Infinity tokens, which
    /// System.Text.Json rejects. Only string values matter here, so each is
    /// read as null: a token that, like them, cannot merge with its
    /// neighbours into something else that parses.
    /// </remarks>
    private static bool TryParsePythonJson(string text, out JsonElement root)
    {
        var json = new StringBuilder(text.Length);
        var inString = false;
        for (var i = 0; i < text.Length; i++)
        {
            var c = text[i];
            if (inString)
            {
                json.Append(c);
                if (c == '\\' && i + 1 < text.Length)
                {
                    json.Append(text[++i]);
                }
                else if (c == '"')
                {
                    inString = false;
                }
                continue;
            }
            var token = NonFiniteToken(text, i);
            if (token > 0)
            {
                json.Append("null");
                i += token - 1;
                continue;
            }
            inString = c == '"';
            json.Append(c);
        }
        try
        {
            using var document = JsonDocument.Parse(json.ToString());
            root = document.RootElement.Clone();
            return true;
        }
        catch (JsonException)
        {
            root = default;
            return false;
        }
    }

    private static int NonFiniteToken(string text, int at)
    {
        foreach (var token in (ReadOnlySpan<string>)["-Infinity", "Infinity", "NaN"])
        {
            if (string.CompareOrdinal(text, at, token, 0, token.Length) == 0)
            {
                return token.Length;
            }
        }
        return 0;
    }

    // Python's `re.match(r"^```(?:json)?\s*(.*?)\s*```$", ..., re.DOTALL)` on
    // stripped text, with Python's whitespace.
    [GeneratedRegex(@"^```(?:json)?[\s\x1c-\x1f]*(.*?)[\s\x1c-\x1f]*```\z", RegexOptions.Singleline | RegexOptions.CultureInvariant)]
    private static partial Regex Fence();
}
