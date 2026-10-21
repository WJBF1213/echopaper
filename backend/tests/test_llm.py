"""Task B5 tests: OpenAI-compatible LLM client.

New hard requirements (2026-10-21 addendum):
- provider=custom is fully user-configurable (base_url/model/api_key)
- context hard cap 256k tokens (262144) + estimator helper
- strictly stateless calls: payload messages == [system, user] exactly
"""
import json

import pytest

from app.services import llm
from app.services.llm import LlmError

CFG = {
    "provider": "zhipu",
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-4.7-flash",
    "api_key": "sk-test",
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm.httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


class FakeClient:
    """Records every POST; replies from a queue of payloads."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def ok(content):
    return FakeResponse(
        {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    )


SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array"}},
    "required": ["items"],
}


@pytest.mark.asyncio
async def test_parses_json_object():
    client = FakeClient([ok(json.dumps({"items": []}))])
    result = await llm.chat_json(
        CFG, "sys", "usr", SCHEMA, client=client
    )
    assert result == {"items": []}
    # request shape: OpenAI compatible endpoint, json_object mode, 2 messages
    call = client.calls[0]
    assert call["url"].endswith("/chat/completions")
    body = call["json"]
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.3
    assert body["max_tokens"] >= 4000
    assert "Bearer sk-test" in call["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_messages_exactly_system_user_no_history():
    """Every call carries exactly [system, user] — no conversation memory."""
    client = FakeClient(
        [ok("{not json"), ok(json.dumps({"items": []}))]
    )
    await llm.chat_json(CFG, "sys-prompt", "usr-prompt", SCHEMA, client=client)
    assert len(client.calls) == 2
    for call in client.calls:
        msgs = call["json"]["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system" and msgs[0]["content"] == "sys-prompt"
        assert msgs[1]["role"] == "user"
    # retry prompt embeds the first failure reason but stays a single user msg
    retry_user = client.calls[1]["json"]["messages"][1]["content"]
    assert "usr-prompt" in retry_user


@pytest.mark.asyncio
async def test_invalid_json_retries_once_then_raises():
    client = FakeClient([ok("{oops"), ok("{still bad")])
    with pytest.raises(LlmError):
        await llm.chat_json(CFG, "s", "u", SCHEMA, client=client)
    assert len(client.calls) == 2  # exactly one retry


@pytest.mark.asyncio
async def test_schema_violation_rejected():
    client = FakeClient(
        [ok(json.dumps({"wrong": 1})), ok(json.dumps({"wrong": 2}))]
    )
    with pytest.raises(LlmError):
        await llm.chat_json(CFG, "s", "u", SCHEMA, client=client)
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_finish_reason_length_raises():
    resp = FakeResponse(
        {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
    )
    client = FakeClient([resp, ok(json.dumps({"items": []}))])
    # truncated output fails validation -> retried; here retry succeeds
    out = await llm.chat_json(CFG, "s", "u", SCHEMA, client=client)
    assert out == {"items": []}


@pytest.mark.asyncio
async def test_custom_provider_uses_user_base_url():
    cfg = {
        "provider": "custom",
        "base_url": "https://my-llm.example.com/v1",
        "model": "my-model",
        "api_key": "my-key",
    }
    client = FakeClient([ok(json.dumps({"items": []}))])
    await llm.chat_json(cfg, "s", "u", SCHEMA, client=client)
    assert client.calls[0]["url"] == "https://my-llm.example.com/v1/chat/completions"
    assert client.calls[0]["json"]["model"] == "my-model"
    assert "Bearer my-key" in client.calls[0]["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_provider_preset_defaults_applied():
    cfg = {"provider": "deepseek", "base_url": "", "model": "", "api_key": "k"}
    client = FakeClient([ok(json.dumps({"items": []}))])
    await llm.chat_json(cfg, "s", "u", SCHEMA, client=client)
    assert client.calls[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert client.calls[0]["json"]["model"] == "deepseek-chat"


def test_max_context_tokens_constant_and_estimator():
    assert llm.MAX_CONTEXT_TOKENS == 262144
    # English heuristic: words × 1.3 (+ overhead at the call site)
    n = llm.estimate_tokens("one two three four five six seven eight nine ten")
    assert n == 13  # 10 words * 1.3


def test_clamp_max_context_hard_cap():
    assert llm.clamp_max_context(1_000_000) == 262144
    assert llm.clamp_max_context(100_000) == 100_000
    assert llm.clamp_max_context(-5) == llm.MIN_CONTEXT_TOKENS


@pytest.mark.asyncio
async def test_test_connection_ok():
    client = FakeClient([ok(json.dumps({"ok": True}))])
    ok_flag, msg = await llm.test_connection(CFG, client=client)
    assert ok_flag is True


@pytest.mark.asyncio
async def test_test_connection_failure():
    client = FakeClient([ok("{bad"), ok("{still bad")])
    ok_flag, msg = await llm.test_connection(CFG, client=client)
    assert ok_flag is False
    assert msg
