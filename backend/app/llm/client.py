"""LLM clients. The model only returns text; parsing and validation live in `reasoning.py`.

`OllamaClient` calls Ollama's OpenAI-compatible chat endpoint with the configured base URL and model.
`FakeLLMClient` replays canned replies so everything above it can be exercised without a model.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Protocol

from app.core.config import get_settings


class LLMError(Exception):
    """The model could not be reached or returned an unusable HTTP response."""


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        reasoning_effort: str | None = "none",
        temperature: float = 0.0,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Normal negotiation calls use fast/no-reasoning mode (DECISIONS.md). On Ollama's OpenAI-compatible endpoint
        # "none" turns qwen3.5:4b's thinking off, like `think: false` on its native API (verified 2026-10-18,
        # Ollama 0.40.6: no reasoning text, ~2.7 s instead of ~23 s on a short prompt); set None to omit.
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.timeout = timeout

    @classmethod
    def from_settings(cls, **kwargs) -> "OllamaClient":
        settings = get_settings()
        return cls(settings.ollama_base_url, settings.ollama_model, **kwargs)

    def complete(self, messages: list[dict[str, str]]) -> str:
        body: dict = {"model": self.model, "messages": messages, "temperature": self.temperature, "stream": False}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            return payload["choices"][0]["message"]["content"] or ""
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError(f"Ollama call failed: {exc}") from exc


class FakeLLMClient:
    """Returns the given replies in order (the last one repeats) and records every call."""

    def __init__(self, replies: Iterable[str]):
        self._replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self._replies:
            raise LLMError("FakeLLMClient has no replies")
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
