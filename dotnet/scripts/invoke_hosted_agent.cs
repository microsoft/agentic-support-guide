#:project ../services/api/AgenticSupportGuide.Api/AgenticSupportGuide.Api.csproj
#:package System.CommandLine

// Invoke a deployed hosted agent over the Responses protocol.
//
// Module 5 uses this to prove the hosted agent works, and to compare it
// against the Module 4 prompt agent. Auth is Entra: the managed endpoint
// accepts a token for the Foundry scope, so no key is involved.
//
// Usage:
//   dotnet run dotnet/scripts/invoke_hosted_agent.cs -- --suffix <your-alias> --question "..."

using System.ClientModel.Primitives;
using System.CommandLine;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using AgenticSupportGuide.Api;
using AgenticSupportGuide.Api.Parity;
using Azure.AI.Projects;
using OpenAI.Responses;

return await InvokeHostedAgent.MainAsync(args);

public static class InvokeHostedAgent
{
    private static readonly string TrackRoot = Path.GetFullPath(Path.Combine(ScriptDir(), ".."));
    private static readonly string EnvFile = Path.Combine(TrackRoot, "services", "api", ".env");
    private const string AgentNamePrefix = "asg-hosted-explainer-";

    private const string DefaultQuestion =
        "What does the dealer group standard say about enquiry response when "
        + "first-response times are behind target?";

    public static async Task<int> MainAsync(string[] args)
    {
        // Must precede parsing: the --suffix default reads the environment, so
        // loading .env afterwards would ignore a suffix set only in that file.
        LoadEnv();

        var suffixOption = new Option<string>("--suffix")
        {
            Description = "Learner suffix. Defaults to WORKSHOP_LEARNER_SUFFIX.",
            DefaultValueFactory = _ => Environment.GetEnvironmentVariable("WORKSHOP_LEARNER_SUFFIX") ?? "",
        };
        var questionOption = new Option<string>("--question") { DefaultValueFactory = _ => DefaultQuestion };
        var command = new RootCommand("Invoke a deployed hosted agent over the Responses protocol.") { suffixOption, questionOption };
        command.SetAction((parsed, _) => RunAsync(parsed.GetValue(suffixOption) ?? "", parsed.GetValue(questionOption) ?? DefaultQuestion));
        // No @file response files: a question starting with "@" is a question, as it is to argparse.
        return await command.Parse(args, new ParserConfiguration { ResponseFileTokenReplacer = null }).InvokeAsync();
    }

    private static async Task<int> RunAsync(string suffixArg, string question)
    {
        var suffix = PyText.Lower(PyText.Strip(suffixArg));
        if (suffix.Length == 0)
        {
            Console.Error.WriteLine("Pass --suffix <your-alias> or set WORKSHOP_LEARNER_SUFFIX.");
            return 2;
        }

        var projectEndpoint = Endpoint();
        if (projectEndpoint.Length == 0)
        {
            Console.Error.WriteLine("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set.");
            return 2;
        }

        var agentName = $"{AgentNamePrefix}{suffix}";
        var project = new AIProjectClient(new Uri(projectEndpoint), Credentials.Default());
        // Binding the agent name here points the Responses client at the hosted
        // agent's managed endpoint. Auth is Entra; no key is involved.
        var client = project.ProjectOpenAIClient.GetProjectResponsesClientForAgentEndpoint(agentName);

        Console.WriteLine($"Agent    : {agentName}");
        try
        {
            var details = (await project.AgentAdministrationClient.GetAgentAsync(agentName)).Value;
            // Module 5 step 6: this principal is the agent's own, not the caller's.
            Console.WriteLine($"Identity : {(details.InstanceIdentity?.PrincipalId is { Length: > 0 } principal ? principal : "(none reported)")}");
        }
        catch (Exception exc)
        {
            // Informational only.
            Console.WriteLine($"Identity : unavailable ({exc.GetType().Name})");
        }
        Console.WriteLine($"Question : {question}\n");

        var started = Stopwatch.StartNew();
        ResponseResult response;
        try
        {
            response = (await client.CreateResponseAsync(model: agentName, userInputText: question)).Value;
        }
        catch (Exception exc)
        {
            // A learner-facing summary.
            Console.Error.WriteLine($"Failed after {PyFloat.Fixed(started.Elapsed.TotalSeconds, 1)}s");
            Console.Error.WriteLine($"{exc.GetType().Name}: {exc.Message}");
            return 1;
        }

        Console.WriteLine($"Answered in {PyFloat.Fixed(started.Elapsed.TotalSeconds, 1)}s\n");
        var text = response.GetOutputText();
        // The raw response, when there is no output text to show.
        Console.WriteLine(text is { Length: > 0 } ? text : PyText.Head(ModelReaderWriter.Write(response).ToString(), 1000));
        return 0;
    }

    private static string Endpoint() =>
        Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") is { Length: > 0 } project
            ? project
            : Environment.GetEnvironmentVariable("AZURE_AI_FOUNDRY_ENDPOINT") ?? "";

    private static void LoadEnv()
    {
        if (!File.Exists(EnvFile))
        {
            return;
        }
        foreach (var raw in PyText.SplitLines(File.ReadAllText(EnvFile)))
        {
            var line = PyText.Strip(raw);
            if (line.Length > 0 && !line.StartsWith('#') && line.Contains('='))
            {
                var at = line.IndexOf('=');
                var key = PyText.Strip(line[..at]);
                if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(key)))
                {
                    Environment.SetEnvironmentVariable(key, PyText.Strip(line[(at + 1)..]));
                }
            }
        }
    }

    private static string ScriptDir([CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;
}
