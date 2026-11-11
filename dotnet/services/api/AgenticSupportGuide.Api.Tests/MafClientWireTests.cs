using System.ClientModel.Primitives;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;
using Azure.AI.Projects;
using Azure.Core;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// What the production client factory actually puts on the wire, captured
/// at the HTTP boundary with a canned Responses API reply.
/// </summary>
public sealed class CapturedResponses
{
    public List<JsonObject> Requests { get; } = [];

    public FoundryResponsesClientFactory Factory(string replyText) =>
        new(
            FakeChatClientFactory.DefaultEndpoint,
            new StaticCredential(),
            new AIProjectClientOptions { Transport = new HttpClientPipelineTransport(new HttpClient(new Handler(this, replyText))) });

    private sealed class Handler(CapturedResponses owner, string replyText) : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = request.Content is null ? "{}" : await request.Content.ReadAsStringAsync(cancellationToken);
            var captured = JsonNode.Parse(body)!.AsObject();
            captured["$method"] = request.Method.Method;
            captured["$path"] = request.RequestUri!.AbsolutePath;
            owner.Requests.Add(captured);
            var reply = new JsonObject
            {
                ["id"] = "resp_test",
                ["object"] = "response",
                ["created_at"] = 1700000000,
                ["status"] = "completed",
                ["model"] = "served-deployment",
                ["output"] = new JsonArray(new JsonObject
                {
                    ["type"] = "message",
                    ["id"] = "msg_test",
                    ["status"] = "completed",
                    ["role"] = "assistant",
                    ["content"] = new JsonArray(new JsonObject
                    {
                        ["type"] = "output_text",
                        ["text"] = replyText,
                        ["annotations"] = new JsonArray(),
                    }),
                }),
                ["usage"] = new JsonObject { ["input_tokens"] = 11, ["output_tokens"] = 7, ["total_tokens"] = 18 },
            };
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(reply.ToJsonString(), Encoding.UTF8, "application/json"),
            };
        }
    }

    private sealed class StaticCredential : TokenCredential
    {
        public override AccessToken GetToken(TokenRequestContext requestContext, CancellationToken cancellationToken) =>
            new("test-token", DateTimeOffset.UtcNow.AddHours(1));

        public override ValueTask<AccessToken> GetTokenAsync(TokenRequestContext requestContext, CancellationToken cancellationToken) =>
            ValueTask.FromResult(GetToken(requestContext, cancellationToken));
    }
}

/// <summary>
/// What the production client factory puts on the wire.
/// </summary>
/// <remarks>
/// The fakes in the other tests replace the client factory, so nothing else
/// checks the request Agent Framework actually sends.
/// </remarks>
public class MafClientWireTests
{
    private const string ReplyText = "{\"ok\": true}";

    private static RoleDefinition Definition() =>
        new(
            "data-analyst-agent",
            "Analyse things.",
            "fake-deployment",
            0.2,
            800,
            PromptEnvelope.LoadResponseSchema(PromptEnvelope.LoadAgentAssets("data-analyst")));

    [Fact]
    public async Task Every_call_disables_storage_and_sends_the_agent_folder_schema()
    {
        var captured = new CapturedResponses();
        var result = await captured.Factory(ReplyText).InvokeAsync(Definition(), "hello", typeof(DataAnalystModelOutput), CancellationToken.None);

        var request = Assert.Single(captured.Requests);
        Assert.False(request["store"]!.GetValue<bool>());
        Assert.Equal("fake-deployment", request["model"]!.GetValue<string>());
        Assert.Equal("Analyse things.", request["instructions"]!.GetValue<string>());
        Assert.Equal(0.2, request["temperature"]!.GetValue<double>(), 6);
        Assert.Equal(800, request["max_output_tokens"]!.GetValue<int>());
        Assert.Equal("hello", request["input"]![0]!["content"]![0]!["text"]!.GetValue<string>());

        var format = request["text"]!["format"]!.AsObject();
        Assert.Equal("json_schema", format["type"]!.GetValue<string>());
        Assert.Equal("DataAnalystModelOutput", format["name"]!.GetValue<string>());
        Assert.True(format["strict"]!.GetValue<bool>());
        Assert.Empty(Conformance.JsonCompare.Differences(JsonNode.Parse(Definition().ResponseSchema!.Value.GetRawText()), format["schema"]));

        Assert.Equal(ReplyText, result.Text);
        Assert.Equal("served-deployment", result.Model);
        Assert.Equal(11, result.InputTokens);
        Assert.Equal(7, result.OutputTokens);
    }

    /// <summary>Agent Framework must not reject it first, or it becomes a provider error.</summary>
    [Fact]
    public async Task An_off_contract_reply_is_returned_for_the_app_to_judge()
    {
        var captured = new CapturedResponses();
        var result = await captured.Factory(ReplyText).InvokeAsync(Definition(), "hello", typeof(DataAnalystModelOutput), CancellationToken.None);
        Assert.Equal(ReplyText, result.Text);
    }
}
