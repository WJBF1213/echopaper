"""LLM client tests (Task B5 + Task 7).

Task 7 requirements:
- provider=custom is fully user-configurable (base_url/model/api_key)
- context hard cap 256k tokens (262144) + estimator helper
- strictly stateless calls: the payload's messages are exactly the
  caller-supplied list (three-part for exam generation); retries rewrite
  only the LAST message, so the stable prefix is byte-identical
- temperature=0.0, usage accounting across three provider field shapes,
  exact-match llm_cache behind cached_chat_json
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

TWO_MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "usr"},
]


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm.httpx.HTTPStatusError("err", request=None, response=self)

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


@pytest.mark.asyncio
async def test_parses_json_object():
    client = FakeClient([ok(json.dumps({"items": []}))])
    result = await llm.chat_json(CFG, TWO_MESSAGES, client=client)
    assert result == {"items": []}
    # request shape: OpenAI compatible endpoint, json_object mode
    call = client.calls[0]
    assert call["url"].endswith("/chat/completions")
    body = call["json"]
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 8192
    assert "Bearer sk-test" in call["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_messages_pass_through_verbatim_retry_keeps_prefix():
    """Payload messages == the caller's list; the retry rewrites only the
    last message in place, so the stable prefix stays byte-identical."""
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "stable frame"},
        {"role": "user", "content": "task frame"},
    ]
    client = FakeClient([ok("{not json"), ok(json.dumps({"items": []}))])
    await llm.chat_json(CFG, messages, client=client)
    assert len(client.calls) == 2
    first = client.calls[0]["json"]["messages"]
    assert first == messages
    retry = client.calls[1]["json"]["messages"]
    assert len(retry) == 3
    # system + stable frame untouched: provider prefix cache stays valid
    assert retry[0] == messages[0]
    assert retry[1] == messages[1]
    # retry prompt embeds the first failure reason in the tail message
    assert "task frame" in retry[2]["content"]


@pytest.mark.asyncio
async def test_invalid_json_retries_once_then_raises():
    client = FakeClient([ok("{oops"), ok("{still bad")])
    with pytest.raises(LlmError):
        await llm.chat_json(CFG, TWO_MESSAGES, client=client)
    assert len(client.calls) == 2  # exactly one retry


@pytest.mark.asyncio
async def test_schema_hint_appended_to_last_message():
    """A non-empty schema hint is joined onto the tail message content."""
    client = FakeClient([ok(json.dumps({"items": []}))])
    await llm.chat_json(
        CFG,
        TWO_MESSAGES,
        schema='{"groups": []}',
        client=client,
    )
    msgs = client.calls[0]["json"]["messages"]
    assert len(msgs) == 2
    assert msgs[1]["content"].endswith('\n{"groups": []}')
    assert msgs[1]["content"].startswith("usr")


@pytest.mark.asyncio
async def test_chat_json_tolerates_code_fences():
    fenced = "```json\n" + json.dumps({"items": [1]}) + "\n```"
    client = FakeClient([ok(fenced)])
    assert await llm.chat_json(CFG, TWO_MESSAGES, client=client) == {
        "items": [1]
    }


@pytest.mark.asyncio
async def test_top_level_non_dict_retried_then_dict_accepted():
    """A provider ignoring response_format may answer with a top-level
    array: that is a parse failure feeding the retry round, never an
    AttributeError crash at the call site (.get on a list)."""
    client = FakeClient([ok(json.dumps([1, 2])), ok(json.dumps({"items": []}))])
    result = await llm.chat_json(CFG, TWO_MESSAGES, client=client)
    assert result == {"items": []}
    assert len(client.calls) == 2
    # the retry carries the reason into the tail message
    assert "not an object" in client.calls[1]["json"]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_top_level_non_dict_always_raises_llm_error():
    client = FakeClient([ok('["a", "b"]'), ok('"plain string"')])
    with pytest.raises(LlmError):
        await llm.chat_json(CFG, TWO_MESSAGES, client=client)
    assert len(client.calls) == 2  # one retry, then LlmError — not AttributeError


@pytest.mark.asyncio
async def test_finish_reason_length_raises():
    resp = FakeResponse(
        {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
    )
    client = FakeClient([resp, ok(json.dumps({"items": []}))])
    # truncated output fails validation -> retried; here retry succeeds
    out = await llm.chat_json(CFG, TWO_MESSAGES, client=client)
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
    await llm.chat_json(cfg, TWO_MESSAGES, client=client)
    assert client.calls[0]["url"] == "https://my-llm.example.com/v1/chat/completions"
    assert client.calls[0]["json"]["model"] == "my-model"
    assert "Bearer my-key" in client.calls[0]["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_provider_preset_defaults_applied():
    cfg = {"provider": "deepseek", "base_url": "", "model": "", "api_key": "k"}
    client = FakeClient([ok(json.dumps({"items": []}))])
    await llm.chat_json(cfg, TWO_MESSAGES, client=client)
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


@pytest.mark.asyncio
async def test_test_connection_surfaces_provider_error_body():
    """A rejected key/model must show the provider's reason, not just 401."""
    resp = FakeResponse(
        {"error": {"message": "Authentication Fails, Your api key is invalid"}},
        status=401,
    )
    ok_flag, msg = await llm.test_connection(CFG, client=FakeClient([resp]))
    assert ok_flag is False
    assert "401" in msg
    assert "api key is invalid" in msg


# ------------------------------------------------- Task 7: messages/usage/cache


def ok_usage(content, usage):
    return FakeResponse(
        {
            "choices": [
                {"message": {"content": content}, "finish_reason": "stop"}
            ],
            "usage": usage,
        }
    )


def test_canonical_json_deterministic():
    a = {"b": 1, "a": {"y": [1, 2], "x": "中文"}}
    b = {"a": {"y": [1, 2], "x": "中文"}, "b": 1}
    assert llm.canonical_json(a) == llm.canonical_json(b)
    # sorted keys, no spaces, non-ASCII kept verbatim
    assert llm.canonical_json(a) == '{"a":{"x":"中文","y":[1,2]},"b":1}'


@pytest.mark.asyncio
async def test_chat_usage_parses_three_providers():
    msgs = [{"role": "user", "content": "hi"}]
    forms = [
        # OpenAI-style nested details
        (
            {
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 7},
            },
            7,
        ),
        # flat prompt_cache_hit_tokens
        (
            {
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "prompt_cache_hit_tokens": 5,
            },
            5,
        ),
        # cache_read_input_tokens
        (
            {
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "cache_read_input_tokens": 4,
            },
            4,
        ),
        # parse order: nested details wins when several fields are present
        (
            {
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 7},
                "prompt_cache_hit_tokens": 5,
                "cache_read_input_tokens": 4,
            },
            7,
        ),
        ({}, 0),
    ]
    for usage_form, cached in forms:
        client = FakeClient([ok_usage("x", usage_form)])
        content, usage = await llm.chat(CFG, msgs, client=client)
        assert content == "x"
        assert usage.prompt_tokens == usage_form.get("prompt_tokens", 0)
        assert usage.completion_tokens == usage_form.get("completion_tokens", 0)
        assert usage.cached_tokens == cached


@pytest.mark.asyncio
async def test_cached_chat_json_hit_and_write(tmp_db):
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "stable transcript + candidates"},
        {"role": "user", "content": "task frame"},
    ]
    client = FakeClient(
        [
            ok_usage(
                json.dumps({"items": [1]}),
                {
                    "prompt_tokens": 20,
                    "completion_tokens": 4,
                    "prompt_cache_hit_tokens": 9,
                },
            )
        ]
    )
    parsed, usage, from_cache = await llm.cached_chat_json(
        tmp_db, CFG, msgs, task="exam:test", client=client
    )
    assert from_cache is False
    assert parsed == {"items": [1]}
    assert usage == llm.ChatUsage(prompt_tokens=20, completion_tokens=4,
                                  cached_tokens=9)
    assert len(client.calls) == 1

    row = tmp_db.execute(
        "SELECT task, model, response_json FROM llm_cache"
    ).fetchone()
    assert row["task"] == "exam:test"
    assert row["model"] == CFG["model"]
    assert json.loads(row["response_json"]) == {"items": [1]}

    # second identical call: served from the table, network client untouched
    parsed2, usage2, from_cache2 = await llm.cached_chat_json(
        tmp_db, CFG, msgs, task="exam:test", client=FakeClient([])
    )
    assert from_cache2 is True
    assert parsed2 == parsed
    assert usage2 == usage

    # api_key is deliberately NOT part of the key: another key still hits
    cfg2 = {**CFG, "api_key": "sk-other"}
    _, _, hit = await llm.cached_chat_json(
        tmp_db, cfg2, msgs, task="exam:test", client=FakeClient([])
    )
    assert hit is True

    assert llm.clear_llm_cache(tmp_db) == 1
    assert llm.clear_llm_cache(tmp_db) == 0


@pytest.mark.asyncio
async def test_cache_key_changes_on_prompt_override(tmp_db):
    from app.services import prompts

    def messages_for(conn, transcript):
        return [
            {
                "role": "system",
                "content": prompts.render_prompt(conn, "exam.system", "zh"),
            },
            {
                "role": "user",
                "content": prompts.render_prompt(
                    conn, "exam.stable_frame", "zh",
                    transcript=transcript, candidates="cand lines",
                ),
            },
            {"role": "user", "content": "task frame"},
        ]

    msgs_one = messages_for(tmp_db, "transcript text one")
    msgs_two = messages_for(tmp_db, "transcript text two")
    assert msgs_one[1]["content"] != msgs_two[1]["content"]

    await llm.cached_chat_json(
        tmp_db, CFG, msgs_one, task="exam:x",
        client=FakeClient([ok(json.dumps({"items": []}))]),
    )
    # different stable-frame content -> different messages -> cache miss
    client = FakeClient([ok(json.dumps({"items": []}))])
    _, _, hit = await llm.cached_chat_json(
        tmp_db, CFG, msgs_two, task="exam:x", client=client
    )
    assert hit is False
    assert len(client.calls) == 1

    # an override that edits the stable-frame template changes the rendered
    # text and therefore the key: previously cached answers are not reused
    prompts.set_override(
        tmp_db, "exam.stable_frame.zh", "O {{transcript}} | {{candidates}}"
    )
    msgs_over = messages_for(tmp_db, "transcript text one")
    assert msgs_over[1]["content"] != msgs_one[1]["content"]
    client2 = FakeClient([ok(json.dumps({"items": []}))])
    _, _, hit2 = await llm.cached_chat_json(
        tmp_db, CFG, msgs_over, task="exam:x", client=client2
    )
    assert hit2 is False
    assert len(client2.calls) == 1


@pytest.mark.asyncio
async def test_chat_default_temperature_zero():
    client = FakeClient([ok("hello")])
    content, usage = await llm.chat(
        CFG, [{"role": "user", "content": "hi"}], client=client
    )
    assert content == "hello"
    assert isinstance(usage, llm.ChatUsage)
    body = client.calls[0]["json"]
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 4096
    assert body["messages"] == [{"role": "user", "content": "hi"}]
