"""Foundry Agent Service integration.

This package isolates all Azure AI Foundry Agent Service SDK usage so
that the rest of the app depends only on the stable internal interface.
Every SDK import lives in `sdk_client.py`.
"""

from .adapter import FoundryRemoteAgentAdapter, RemoteAgentResponse
from .bindings import (
    AgentBinding,
    BindingFileError,
    hash_endpoint,
    hash_instructions,
    load_bindings,
    save_bindings,
)
from .errors import (
    AuthError,
    ConfigurationError,
    ContentFilterError,
    FoundryProviderError,
    FoundryRunError,
    FoundryTimeoutError,
    RequiresActionError,
    ThrottledError,
)
from .prompt_envelope import (
    AGENTS_DIR,
    RUNTIME_ENVELOPE,
    AgentAssets,
    compose_instructions,
    instructions_hash,
    load_agent_assets,
)
from .sdk_client import FoundryAgentClient, FoundryAgentClientProtocol, RunResult

__all__ = [
    "AGENTS_DIR",
    "AgentAssets",
    "AgentBinding",
    "AuthError",
    "BindingFileError",
    "ConfigurationError",
    "ContentFilterError",
    "FoundryAgentClient",
    "FoundryAgentClientProtocol",
    "FoundryProviderError",
    "FoundryRemoteAgentAdapter",
    "FoundryRunError",
    "FoundryTimeoutError",
    "RUNTIME_ENVELOPE",
    "RemoteAgentResponse",
    "RequiresActionError",
    "RunResult",
    "ThrottledError",
    "compose_instructions",
    "hash_endpoint",
    "hash_instructions",
    "instructions_hash",
    "load_agent_assets",
    "load_bindings",
    "save_bindings",
]
