import asyncio
import json

import httpx
import pytest

from app import llm

A = llm.Provider("a", "https://a.test/v1", "model-a", "key-a")
B = llm.Provider("b", "https://b.test/v1", "model-b", "key-b")


@pytest.fixture
def mock_http(monkeypatch):
    """Route all httpx.AsyncClient traffic through a handler set by the test."""
    state = {}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return state["handler"](request)

    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    return state


def chat_json(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def sse(*deltas, done=True):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': d}}]})}\n\n" for d in deltas]
    if done:
        lines.append("data: [DONE]\n\n")
    return httpx.Response(200, content="".join(lines).encode(), headers={"content-type": "text/event-stream"})


async def collect(gen):
    return [ev async for ev in gen]


@pytest.mark.parametrize("failure", [429, 500, 503, "timeout"])
def test_complete_fails_over(mock_http, failure):
    def handler(req):
        if req.url.host == "a.test":
            if failure == "timeout":
                raise httpx.ReadTimeout("slow", request=req)
            return httpx.Response(failure)
        return chat_json("from b")

    mock_http["handler"] = handler
    text, provider = asyncio.run(llm.complete([{"role": "user", "content": "q"}], [A, B]))
    assert (text, provider.name) == ("from b", "b")


def test_complete_uses_first_provider_when_healthy(mock_http):
    seen = []

    def handler(req):
        seen.append(req.url.host)
        assert req.headers["authorization"] == "Bearer key-a"
        return chat_json("from a")

    mock_http["handler"] = handler
    text, provider = asyncio.run(llm.complete([], [A, B]))
    assert provider.name == "a" and seen == ["a.test"]


def test_complete_all_fail(mock_http):
    mock_http["handler"] = lambda req: httpx.Response(429)
    with pytest.raises(llm.AllProvidersFailed):
        asyncio.run(llm.complete([], [A, B]))


def test_stream_fails_over_before_first_token(mock_http):
    mock_http["handler"] = lambda req: httpx.Response(429) if req.url.host == "a.test" else sse("Hel", "lo")
    events = asyncio.run(collect(llm.stream([], [A, B])))
    assert events[0] == {"type": "provider", "provider": "b", "model": "model-b"}
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Hello"
    assert events[-1] == {"type": "done", "provider": "b"}


def test_stream_does_not_switch_mid_answer(mock_http):
    calls = []

    def handler(req):
        calls.append(req.url.host)
        if req.url.host == "a.test":
            body = f"data: {json.dumps({'choices': [{'delta': {'content': 'partial'}}]})}\n\n"
            body += 'data: {"error": {"message": "boom"}}\n\n'
            return httpx.Response(200, content=body.encode())
        return sse("other answer")

    mock_http["handler"] = handler
    events = asyncio.run(collect(llm.stream([], [A, B])))
    assert calls == ["a.test"]
    assert [e["type"] for e in events] == ["provider", "token", "error"]


def test_stream_without_providers_reports_error():
    events = asyncio.run(collect(llm.stream([], [])))
    assert events == [{"type": "error", "message": "No LLM provider is configured"}]


def test_configured_providers_follow_order_and_skip_missing():
    s = llm.Settings(
        groq_api_key="g", gemini_api_key="m", openrouter_api_key="",
        ollama_url="", provider_order=["gemini", "openrouter", "groq"],
    )
    assert [p.name for p in llm.configured_providers(s)] == ["gemini", "groq"]
