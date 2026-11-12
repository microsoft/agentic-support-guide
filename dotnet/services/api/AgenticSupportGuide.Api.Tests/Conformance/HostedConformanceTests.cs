using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.Parity;
using AgenticSupportGuide.Hosted;

namespace AgenticSupportGuide.Api.Tests.Conformance;

/// <summary>
/// The hosted agent's input bounds and output gate, against the Python
/// track's recordings.
/// </summary>
public class HostedConformanceTests
{
    [Fact]
    public void Hosted_gate_gives_the_same_answers()
    {
        var golden = Goldens.Load("hosted.json").AsObject();
        // The golden is what this track must match, but xUnit wants the constant first.
        Assert.Equal(SafetyGate.EmptyQuestionReply, golden["empty_question_reply"]!.GetValue<string>());
        Assert.Equal(SafetyGate.QuestionMaxLen, golden["question_max_len"]!.GetValue<int>());

        var mismatches = new List<string>();
        foreach (var question in golden["questions"]!.AsArray())
        {
            var texts = question!["texts"]!.AsArray().Select(Text).ToList();
            var bounded = SafetyGate.BoundedQuestion(texts);
            var fenced = bounded.Length > 0 ? TextRecord(PromptBlocks.WrapUntrusted("user question", bounded)) : null;
            if (!JsonNode.DeepEquals(question["bounded"], TextRecord(bounded)) || !JsonNode.DeepEquals(question["fenced"], fenced))
            {
                mismatches.Add($"question {question["texts"]!.ToJsonString()}: bounded or fenced text differs");
            }
        }
        foreach (var answer in golden["answers"]!.AsArray())
        {
            var text = answer!["answer"]!.GetValue<string>();
            var (plain, gated) = (SafetyGate.PlainText(text), SafetyGate.Gate(text));
            if (plain != answer["plain_text"]!.GetValue<string>() || gated != answer["gate"]!.GetValue<string>())
            {
                mismatches.Add($"{PyJson.Quote(text)}: got plain_text {PyJson.Quote(plain)}, gate {PyJson.Quote(gated)}");
            }
        }
        Assert.True(mismatches.Count == 0, string.Join("\n", mismatches));
    }

    // A text block, or a long run of one character stored as {"repeat", "count"}.
    private static string Text(JsonNode? spec) => spec is JsonValue value
        ? value.GetValue<string>()
        : string.Concat(Enumerable.Repeat(spec!["repeat"]!.GetValue<string>(), spec["count"]!.GetValue<int>()));

    // A text inline when short, otherwise its length and hash.
    private static JsonObject TextRecord(string text) => PyText.Len(text) <= 300
        ? new JsonObject { ["text"] = text }
        : new JsonObject { ["length"] = PyText.Len(text), ["sha256"] = ScenarioReplay.Sha256(text) };
}
