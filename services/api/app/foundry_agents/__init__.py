"""Azure AI Foundry integration via Microsoft Agent Framework.

Agents are *ephemeral*: each call assembles the agent in-process from
`/agents/<id>/agent.md` and runs it against the Foundry project's Responses
API. Nothing is persisted server-side, so there are no agent resources to
create, migrate, or collide on.

All Agent Framework SDK imports live in `maf_client.py`.
"""

from .error_mapping import map_provider_error
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
from .maf_client import FoundryResponsesClientFactory, default_credential_factory
from .maf_runtime import (
    PROVIDER_ID,
    MafAgentRuntime,
    RoleDefinition,
    RoleResponse,
)
from .prompt_envelope import (
    AGENTS_DIR,
    RUNTIME_ENVELOPE,
    AgentAssets,
    compose_instructions,
    declared_response_format,
    instructions_hash,
    load_agent_assets,
)
from .role_definitions import (
    REQUIRED_ROLES,
    ROLE_DIRS,
    load_role_definitions,
    missing_model_deployments,
    model_deployment_env_names,
)

__all__ = [
    "AGENTS_DIR",
    "PROVIDER_ID",
    "REQUIRED_ROLES",
    "ROLE_DIRS",
    "RUNTIME_ENVELOPE",
    "AgentAssets",
    "AuthError",
    "ConfigurationError",
    "ContentFilterError",
    "FoundryProviderError",
    "FoundryResponsesClientFactory",
    "FoundryRunError",
    "FoundryTimeoutError",
    "MafAgentRuntime",
    "RequiresActionError",
    "RoleDefinition",
    "RoleResponse",
    "ThrottledError",
    "compose_instructions",
    "declared_response_format",
    "default_credential_factory",
    "instructions_hash",
    "load_agent_assets",
    "load_role_definitions",
    "map_provider_error",
    "missing_model_deployments",
    "model_deployment_env_names",
]
