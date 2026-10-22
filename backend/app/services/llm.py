"""OpenAI-compatible LLM client (Task B5; overhauled in Task 7).

Hard requirements (design spec §2.3 + §8, 2026-10-21/22 addenda):
- Every call is strictly stateless: the caller supplies the whole
  ``messages`` list (exam generation sends the three-part layout of
  design §8.1: system -> stable frame -> task frame). No cross-call or
  cross-material history is ever accumulated; retries rewrite only the
  LAST message in place.
- Sampling: ``temperature=0.0`` so provider-side prefix caching and the
  local response cache see byte-stable requests; ``max_tokens`` is a
  parameter (exam generation defaults to 8192).
- Provider prefix caches are exploited purely by message ordering; no
  cache-control parameters are sent (§8.5).
- Local exact-match response cache in the ``llm_cache`` table (§8.3) via
  :func:`cached_chat_json`; usage accounting per §8.4.
- Connections are reused through a module-level lazy ``httpx.AsyncClient``
  singleton; an explicit ``client=`` argument (tests, callers with their
  own lifecycle) always wins and is never closed here.
- provider=custom is fully user-configurable (base_url/model/api_key).
- Total context hard cap: 256k tokens (262144). ``max_context_tokens`` in
  config may lower it but can NEVER raise it above the cap.

Only stdlib + httpx; no framework imports (portable layer).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from app import db, i18n
from app.services.prompts import PROMPTS_VERSION

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
MAX_TOKENS = 4096  # chat() default; chat_json() defaults to 8192 (§8.2)

# Module-level lazy singleton: one pooled AsyncClient per process. Never
# closed by individual calls; recreated if the previous one went away
# (e.g. its event loop died).
_shared_client: httpx.AsyncClient | None = None


def _shared_http_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S)
    return _shared_client


class LlmError(Exception):
    """Raised when the LLM cannot return usable JSON."""


@dataclass
class ChatUsage:
    """Token accounting for one call (design §8.4).

    ``cached_tokens`` parse order: ``usage.prompt_tokens_details.
    cached_tokens`` -> ``usage.prompt_cache_hit_tokens`` ->
    ``usage.cache_read_input_tokens`` -> 0 (OpenAI / GLM / DeepSeek).
    """

    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int


def canonical_json(obj: Any) -> str:
    """Byte-stable JSON used in cache keys and prompts (§8.1)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


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
        raise LlmError(i18n.t("llm.incomplete", provider=provider))
    return base_url.rstrip("/"), model, api_key


def _extract_json(content: str) -> Any:
    """Parse JSON, tolerating markdown code fences."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return json.loads(text)


def _parse_usage(raw: Any) -> ChatUsage:
    if not isinstance(raw, Mapping):
        return ChatUsage(0, 0, 0)

    def _count(name: str) -> int:
        v = raw.get(name)
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        v = details.get("cached_tokens")
        if isinstance(v, int) and not isinstance(v, bool):
            cached = v
    if not cached:
        cached = _count("prompt_cache_hit_tokens")
    if not cached:
        cached = _count("cache_read_input_tokens")
    return ChatUsage(
        prompt_tokens=_count("prompt_tokens"),
        completion_tokens=_count("completion_tokens"),
        cached_tokens=cached,
    )


async def _request(
    client,
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    *,
    json_mode: bool,
) -> tuple[str, ChatUsage]:
    """One POST round trip; raises LlmError on a truncated finish."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.post(
        f"{base_url}/chat/completions", json=payload, headers=headers
    )
    resp.raise_for_status()
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    finish = choice.get("finish_reason")
    content = (choice.get("message") or {}).get("content", "")
    usage = _parse_usage(data.get("usage"))
    if finish not in ("stop", None):
        raise LlmError(i18n.t("llm.truncated", reason=finish))
    return content, usage


async def chat(
    cfg: Mapping | Any,
    messages: list[dict],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    client=None,
) -> tuple[str, ChatUsage]:
    """One stateless completion round trip; returns (content, usage)."""
    base_url, model, api_key = resolve(cfg)
    if client is None:
        client = _shared_http_client()
    return await _request(
        client, base_url, model, api_key, messages,
        max_tokens, temperature, json_mode=False,
    )


async def _chat_json_core(
    cfg: Mapping | Any,
    messages: list[dict],
    *,
    schema: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.0,
    client=None,
) -> tuple[dict, ChatUsage]:
    """Stateless JSON call with one retry round appending the failure
    reason to the LAST message (prefix stability: earlier messages are
    never rewritten). The parsed result is guaranteed to be a dict —
    top-level arrays/strings are treated as parse failures and retried.
    Deeper structural validation is the caller's job; the schema hint
    travels inside the prompt itself."""
    base_url, model, api_key = resolve(cfg)
    if client is None:
        client = _shared_http_client()
    msgs = [dict(m) for m in messages]
    if schema:
        msgs[-1] = {**msgs[-1], "content": f"{msgs[-1]['content']}\n{schema}"}
    last_error = ""
    for _attempt in range(2):
        try:
            # snapshot per attempt: the client may hold the payload object
            # beyond the call, and the retry below rewrites the tail in place
            content, usage = await _request(
                client, base_url, model, api_key, [dict(m) for m in msgs],
                max_tokens, temperature, json_mode=True,
            )
            obj = _extract_json(content)
            if not isinstance(obj, dict):
                # A provider ignoring response_format may answer with a
                # top-level array/string; callers .get() on the result, so
                # treat it as a parse failure and retry with the reason.
                raise ValueError("top-level JSON was not an object")
            return obj, usage
        except (ValueError, LlmError) as exc:
            last_error = str(exc)
            msgs[-1] = {
                **msgs[-1],
                "content": i18n.t(
                    "llm.retry_hint", user=msgs[-1]["content"], error=last_error
                ),
            }
    raise LlmError(i18n.t("llm.invalid", error=last_error))


async def chat_json(
    cfg: Mapping | Any,
    messages: list[dict],
    *,
    schema: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.0,
    client=None,
) -> dict:
    """Stateless schema-hinted JSON call; one retry round, then LlmError."""
    obj, _usage = await _chat_json_core(
        cfg, messages, schema=schema, max_tokens=max_tokens,
        temperature=temperature, client=client,
    )
    return obj


def _cache_key(
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    material = canonical_json(
        [PROMPTS_VERSION, base_url, model, temperature, max_tokens, messages]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def cached_chat_json(
    conn,
    cfg: Mapping | Any,
    messages: list[dict],
    *,
    task: str,
    schema: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.0,
    client=None,
) -> tuple[dict, ChatUsage, bool]:
    """chat_json behind the exact-match ``llm_cache`` table (§8.3).

    Returns ``(parsed, usage, from_cache)``. The key hashes
    [PROMPTS_VERSION, base_url, model, temperature, max_tokens, messages];
    the api_key is deliberately NOT part of it. A miss calls the provider
    and stores the parsed response together with the usage triple.
    """
    base_url, model, _api_key = resolve(cfg)
    key = _cache_key(base_url, model, messages, temperature, max_tokens)
    if conn is not None:
        row = conn.execute(
            "SELECT response_json, prompt_tokens, completion_tokens,"
            " cached_tokens FROM llm_cache WHERE cache_key=?",
            (key,),
        ).fetchone()
        if row is not None:
            return (
                json.loads(row["response_json"]),
                ChatUsage(
                    prompt_tokens=row["prompt_tokens"] or 0,
                    completion_tokens=row["completion_tokens"] or 0,
                    cached_tokens=row["cached_tokens"] or 0,
                ),
                True,
            )
    obj, usage = await _chat_json_core(
        cfg, messages, schema=schema, max_tokens=max_tokens,
        temperature=temperature, client=client,
    )
    if conn is not None:
        with db._write_lock:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO llm_cache(cache_key, task, model,"
                    " response_json, prompt_tokens, completion_tokens,"
                    " cached_tokens, created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        key,
                        task,
                        model,
                        canonical_json(obj),
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        usage.cached_tokens,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
    return obj, usage, False


def clear_llm_cache(conn) -> int:
    """Delete every cached response; returns the number of rows removed."""
    with db._write_lock:
        with conn:
            cur = conn.execute("DELETE FROM llm_cache")
            return cur.rowcount


async def test_connection(
    cfg: Mapping | Any, client=None
) -> tuple[bool, str]:
    """Probe the configured provider with a tiny JSON round-trip."""
    try:
        await chat_json(
            cfg,
            [
                {
                    "role": "system",
                    "content": "You are a connectivity probe. Reply with"
                    " JSON only.",
                },
                {"role": "user", "content": 'Return exactly {"ok": true}'},
            ],
            client=client,
        )
        return True, i18n.t("llm.probe_ok")
    except httpx.HTTPStatusError as exc:
        # Providers put the actionable reason in the body ("Model Not Exist",
        # "Authentication Fails", ...); the bare status line hides it.
        response = exc.response
        detail = ""
        if response is not None:
            try:
                detail = json.dumps(response.json(), ensure_ascii=False)
            except Exception:
                detail = (getattr(response, "text", "") or "").strip()
        status = getattr(response, "status_code", "")
        return False, f"HTTP {status}：{(detail or str(exc))[:300]}"
    except (LlmError, httpx.HTTPError) as exc:
        return False, str(exc)
