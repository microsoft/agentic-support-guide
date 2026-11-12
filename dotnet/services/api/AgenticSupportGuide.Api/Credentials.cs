using Azure.Identity;

namespace AgenticSupportGuide.Api;

/// <summary>The credential every Azure call in this track makes.</summary>
/// <remarks>
/// <see cref="DefaultAzureCredential"/> without the Visual Studio and VS Code
/// sign-ins. In .NET those come before the Azure CLI in the chain, so a laptop
/// signed in to Visual Studio with another account would call Foundry as that
/// account and be refused, where the Python track uses your <c>az login</c>.
/// Without them, both tracks resolve to the same identity: the managed
/// identity when deployed, the Azure CLI on a laptop.
/// </remarks>
public static class Credentials
{
    public static DefaultAzureCredential Default() => new(new DefaultAzureCredentialOptions
    {
        ExcludeVisualStudioCredential = true,
        ExcludeVisualStudioCodeCredential = true,
    });
}
