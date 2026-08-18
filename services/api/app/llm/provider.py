"""LLM provider interface and implementations.

Two implementations:

- :class:`AzureFoundryLlmProvider` uses `openai.AzureOpenAI` with a bearer
  token from `azure-identity` (`DefaultAzureCredential`). Keyless auth.
- :class:`MockLlmProvider` is used only for tests and offline development
  when `ENABLE_MOCK_LLM=true`.

Provider selection is done via FastAPI dependency injection so tests can
override without touching process environment.
"""

from __future__ import annotations

import json
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class LlmError(Exception):
    """Base class for provider errors classified by category."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class LlmCallResult:
    content: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


class LlmProvider(ABC):
    """Narrow interface every agent uses."""

    name: str
    model: str
    display_name: str = "unknown provider"

    @abstractmethod
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        timeout_seconds: float,
        response_schema_name: str,
    ) -> LlmCallResult:  # pragma: no cover - interface
        ...


def _sleep_with_jitter(base_seconds: float, attempt: int, cap: float = 8.0) -> None:
    delay = min(cap, base_seconds * (2 ** (attempt - 1)))
    delay = delay * (0.5 + random.Random(attempt).random() / 2)
    time.sleep(delay)


class AzureFoundryLlmProvider(LlmProvider):
    """Azure OpenAI / Azure AI Foundry provider using keyless auth."""

    name = "azure-openai"
    display_name = "Azure AI Foundry"

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str,
    ) -> None:
        try:
            from azure.identity import (
                DefaultAzureCredential,
                get_bearer_token_provider,
            )
            from openai import AzureOpenAI
        except ImportError as exc:
            raise LlmError(
                "provider_missing",
                f"Azure AI Foundry SDK not installed: {exc}",
            ) from exc

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        self._client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
        self._deployment = deployment
        self.model = deployment

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        timeout_seconds: float,
        response_schema_name: str,
    ) -> LlmCallResult:
        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                completion = self._client.chat.completions.create(
                    model=self._deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_output_tokens,
                    response_format={"type": "json_object"},
                    timeout=timeout_seconds,
                )
            except Exception as exc:  # pragma: no cover - live network
                last_error = exc
                category = self._classify(exc)
                if category in {"throttling", "provider_error"} and attempt < 3:
                    _sleep_with_jitter(0.75, attempt)
                    continue
                if category == "timeout":
                    raise LlmError("timeout", str(exc)) from exc
                if category == "content_filter":
                    raise LlmError("content_filter", str(exc)) from exc
                raise LlmError(category, str(exc)) from exc
            content = completion.choices[0].message.content or ""
            usage = getattr(completion, "usage", None)
            return LlmCallResult(
                content=content,
                provider=self.name,
                model=self._deployment,
                latency_ms=int((time.monotonic() - started) * 1000),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            )
        raise LlmError("provider_error", f"exhausted retries: {last_error}")

    @staticmethod
    def _classify(exc: Exception) -> str:  # pragma: no cover - live network
        msg = str(exc).lower()
        if "content" in msg and "filter" in msg:
            return "content_filter"
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
        status = getattr(exc, "status_code", None)
        if status == 429:
            return "throttling"
        if status and 500 <= status < 600:
            return "provider_error"
        return "provider_error"


class MockLlmProvider(LlmProvider):
    """Deterministic mock provider. Test-only. Injected via dependency overrides."""

    name = "mock"
    model = "mock-reasoner-v0"
    display_name = "test double (not for demo)"

    def __init__(self, canned_responses: dict[str, dict[str, Any]] | None = None) -> None:
        self._canned = canned_responses or {}
        self.calls: list[dict[str, Any]] = []

    def register(self, schema_name: str, payload: dict[str, Any]) -> None:
        self._canned[schema_name] = payload

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        timeout_seconds: float,
        response_schema_name: str,
    ) -> LlmCallResult:
        started = time.monotonic()
        self.calls.append(
            {
                "schema": response_schema_name,
                "system_len": len(system_prompt),
                "user_len": len(user_prompt),
            }
        )
        payload = self._canned.get(response_schema_name)
        if payload is None:
            raise LlmError(
                "provider_error",
                f"MockLlmProvider missing response for '{response_schema_name}'",
            )
        content = json.dumps(payload)
        return LlmCallResult(
            content=content,
            provider=self.name,
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=len(system_prompt) // 4 + len(user_prompt) // 4,
            completion_tokens=len(content) // 4,
        )
