"""LLM provider clients and failover.

Groq, OpenRouter, Gemini and Ollama all expose an OpenAI-compatible
chat-completions endpoint, so one client covers all four.

Providers are tried in PROVIDER_ORDER. A timeout, connection error, 429 or 5xx
(or any other failure before the first token) moves to the next provider. Once
a stream has produced output, a failure ends the stream with an error instead
of switching providers mid-answer.
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from app.config import Settings, settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    api_key: str = ""
    headers: dict = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def request_headers(self) -> dict:
        h = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider = provider


class AllProvidersFailed(Exception):
    pass


def configured_providers(s: Settings = settings) -> list[Provider]:
    """Providers that have credentials, in PROVIDER_ORDER."""
    known: dict[str, Provider] = {}
    if s.groq_api_key:
        known["groq"] = Provider("groq", "https://api.groq.com/openai/v1", s.groq_model, s.groq_api_key)
    if s.openrouter_api_key:
        known["openrouter"] = Provider(
            "openrouter",
            "https://openrouter.ai/api/v1",
            s.openrouter_model,
            s.openrouter_api_key,
            {"X-Title": "RAG PDF Chat"},
        )
    if s.gemini_api_key:
        known["gemini"] = Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            s.gemini_model,
            s.gemini_api_key,
        )
    if s.ollama_url:
        known["ollama"] = Provider("ollama", s.ollama_url.rstrip("/") + "/v1", s.ollama_model)
    return [known[name] for name in s.provider_order if name in known]


def _describe_status(resp: httpx.Response) -> str:
    if resp.status_code == 429:
        return "rate limited (429)"
    if resp.status_code >= 500:
        return f"server error ({resp.status_code})"
    return f"HTTP {resp.status_code}"


def _body(provider: Provider, messages: list[dict], stream: bool) -> dict:
    return {
        "model": provider.model,
        "messages": messages,
        "temperature": 0.1,
        "stream": stream,
    }


async def _complete_one(client: httpx.AsyncClient, provider: Provider, messages: list[dict]) -> str:
    try:
        resp = await client.post(
            provider.url, headers=provider.request_headers(), json=_body(provider, messages, False)
        )
    except httpx.TimeoutException:
        raise ProviderError(provider.name, "timeout")
    except httpx.HTTPError as exc:
        raise ProviderError(provider.name, f"connection error: {exc.__class__.__name__}")
    if resp.status_code != 200:
        raise ProviderError(provider.name, _describe_status(resp))
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError):
        raise ProviderError(provider.name, "malformed response")


async def complete(
    messages: list[dict], providers: list[Provider] | None = None, timeout: float | None = None
) -> tuple[str, Provider]:
    providers = configured_providers() if providers is None else providers
    if not providers:
        raise AllProvidersFailed("No LLM provider is configured")
    errors = []
    async with httpx.AsyncClient(timeout=timeout or settings.llm_timeout_seconds) as client:
        for provider in providers:
            try:
                return await _complete_one(client, provider, messages), provider
            except ProviderError as exc:
                log.warning("LLM provider failed, trying next: %s", exc)
                errors.append(str(exc))
    raise AllProvidersFailed("All providers failed: " + "; ".join(errors))


async def _stream_one(
    client: httpx.AsyncClient, provider: Provider, messages: list[dict]
) -> AsyncIterator[str]:
    """Yield content deltas. Raises ProviderError on any failure."""
    try:
        async with client.stream(
            "POST", provider.url, headers=provider.request_headers(), json=_body(provider, messages, True)
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raise ProviderError(provider.name, _describe_status(resp))
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    payload = json.loads(data)
                except ValueError:
                    continue
                if "error" in payload:
                    raise ProviderError(provider.name, "error in stream")
                choices = payload.get("choices") or []
                if choices:
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
    except httpx.TimeoutException:
        raise ProviderError(provider.name, "timeout")
    except httpx.HTTPError as exc:
        raise ProviderError(provider.name, f"connection error: {exc.__class__.__name__}")


async def stream(
    messages: list[dict], providers: list[Provider] | None = None, timeout: float | None = None
) -> AsyncIterator[dict]:
    """Yield events: {"type": "provider"|"token"|"error"|"done", ...}."""
    providers = configured_providers() if providers is None else providers
    if not providers:
        yield {"type": "error", "message": "No LLM provider is configured"}
        return
    errors = []
    async with httpx.AsyncClient(timeout=timeout or settings.llm_timeout_seconds) as client:
        for provider in providers:
            started = False
            try:
                async for delta in _stream_one(client, provider, messages):
                    if not started:
                        started = True
                        yield {"type": "provider", "provider": provider.name, "model": provider.model}
                    yield {"type": "token", "text": delta}
                if not started:
                    raise ProviderError(provider.name, "empty response")
                yield {"type": "done", "provider": provider.name}
                return
            except ProviderError as exc:
                if started:
                    # Never splice a second model's answer onto a partial one.
                    log.warning("LLM provider failed mid-stream: %s", exc)
                    yield {"type": "error", "message": "The answer was interrupted. Please try again."}
                    return
                log.warning("LLM provider failed, trying next: %s", exc)
                errors.append(str(exc))
    yield {"type": "error", "message": "All providers failed: " + "; ".join(errors)}
