"""Thin, swappable LLM client layer (Anthropic, OpenAI, or offline demo mode)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> LLMResponse: ...


class AnthropicClient:
    def __init__(self, model: str):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model
        self.name = f"anthropic:{model}"

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> LLMResponse:
        t0 = time.perf_counter()
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=0,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return LLMResponse(text, msg.usage.input_tokens, msg.usage.output_tokens, time.perf_counter() - t0)


class OpenAIClient:
    def __init__(self, model: str):
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model
        self.name = f"openai:{model}"

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> LLMResponse:
        t0 = time.perf_counter()
        r = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        u = r.usage
        return LLMResponse(r.choices[0].message.content or "", u.prompt_tokens if u else 0,
                           u.completion_tokens if u else 0, time.perf_counter() - t0)


class OfflineClient:
    """No-API-key demo mode.

    It does not generate SQL; the copilot instead reuses the SQL of the closest
    verified example when similarity is high enough. Useful for trying the UI,
    running CI and showing the retrieval layer, but answers are limited to
    questions close to the example library.
    """

    name = "offline"

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> LLMResponse:
        raise RuntimeError("Offline mode cannot generate text.")


def make_client(provider: str, anthropic_model: str, openai_model: str) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(anthropic_model)
    if provider == "openai":
        return OpenAIClient(openai_model)
    if provider == "offline":
        return OfflineClient()
    raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Use anthropic, openai, offline or auto.")
