"""OpenAI-compatible LLM client (Task B5).

Hard requirements (design spec §2.3, 2026-10-21 addendum):
- Every call is a strictly stateless single-shot request: the payload's
  ``messages`` array contains exactly [system, user] — never any cross-call
  or cross-material history.
- Total context hard cap: 256k tokens (262144). ``max_context_tokens`` in
  config may lower it but can NEVER raise it above the cap.
- provider=custom is fully user-configurable (base_url/model/api_key).

Only stdlib + httpx + jsonschema; no framework imports (portable layer).
"""
from __future__ import annotations

import json
import math
from typing import Any, Mapping

import httpx
import jsonschema

MAX_CONTEXT_TOKENS = 262144  # 256k hard cap (input+output), not exceedable
MIN_CONTEXT_TOKENS = 4096
PROMPT_OVERHEAD_TOKENS = 200  # scaffolding around the user payload

# Provider presets. "custom" leaves everything to the user.
# NOTE dashscope: use the qwen-flash series API name; verify against the
# current DashScope docs when used in production (plan B5 note).
PROVIDERS: dict[str, dict] = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7-flash",
    },
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-flash",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "custom": {"base_url": "", "model": ""},
}

REQUEST_TIMEOUT_S = 120.0
TEMPERATURE = 0.3
MAX_TOKENS = 4096


class LlmError(Exception):
    """Raised when the LLM cannot return schema-valid JSON."""


def estimate_tokens(text: str) -> int:
    """Rough token estimate for mixed EN/CJK text (words × 1.3)."""
    if not text:
        return 0
    words = len(text.split())
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(math.ceil(words * 1.3 + cjk))


def clamp_max_context(value: Any) -> int:
    """User setting may lower the budget but never exceed the hard cap."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return MAX_CONTEXT_TOKENS
    return max(MIN_CONTEXT_TOKENS, min(v, MAX_CONTEXT_TOKENS))


def _cfg_value(cfg: Mapping | Any, key: str) -> Any:
    if isinstance(cfg, Mapping):
        return cfg.get(key)
    return getattr(cfg, key, None)


def resolve(cfg: Mapping | Any) -> tuple[str, str, str]:
    """Resolve (base_url, model, api_key) — cfg wins over preset defaults."""
    provider = (_cfg_value(cfg, "provider") or "zhipu").strip()
    preset = PROVIDERS.get(provider, PROVIDERS["custom"])
    base_url = (_cfg_value(cfg, "base_url") or preset["base_url"]).strip()
    model = (_cfg_value(cfg, "model") or preset["model"]).strip()
    api_key = (_cfg_value(cfg, "api_key") or "").strip()
    if not base_url or not model:
        raise LlmError(
            f"LLM 配置不完整：provider={provider} 需要 base_url 与 model"
        )
    return base_url.rstrip("/"), model, api_key


def _extract_json(content: str) -> Any:
    """Parse JSON, tolerating markdown code fences."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return json.loads(text)


async def chat_json(
    cfg: Mapping | Any,
    system: str,
    user: str,
    schema: dict,
    client=None,
) -> dict:
    """Single stateless chat call returning schema-validated JSON.

    One retry round carrying the previous failure reason; then LlmError.
    The retry stays a single [system, user] request (reason embedded in
    the user turn) — no conversation history is ever accumulated.
    """
    base_url, model, api_key = resolve(cfg)
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S)
    try:
        user_turn = user
        last_error = ""
        for _attempt in range(2):
            payload = {
                "model": model,
                # strictly stateless: exactly system + user
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_turn},
                ],
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            resp = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            finish = choice.get("finish_reason")
            content = (choice.get("message") or {}).get("content", "")
            try:
                if finish not in ("stop", None):
                    raise LlmError(f"finish_reason={finish}（输出被截断）")
                obj = _extract_json(content)
                jsonschema.validate(obj, schema)
                return obj
            except (ValueError, jsonschema.ValidationError, LlmError) as exc:
                last_error = str(exc)
                user_turn = (
                    f"{user}\n\n上一次返回不符合要求：{last_error}\n"
                    "请严格返回符合要求的 JSON 对象，不要任何多余文本。"
                )
        raise LlmError(f"LLM 返回不符合要求（已重试一次）：{last_error}")
    finally:
        if own_client:
            await client.aclose()


async def test_connection(
    cfg: Mapping | Any, client=None
) -> tuple[bool, str]:
    """Probe the configured provider with a tiny JSON round-trip."""
    try:
        await chat_json(
            cfg,
            "You are a connectivity probe. Reply with JSON only.",
            'Return exactly {"ok": true}',
            {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            client=client,
        )
        return True, "连接正常"
    except (LlmError, httpx.HTTPError) as exc:
        return False, str(exc)
