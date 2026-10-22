"""Sentence translation service: gtx -> MyMemory -> LLM, plus the
redesign §7.2 LLM-first batch channel ``translate_llm_batch`` used by
the ingestion pipeline (the per-sentence channels remain its fallback).

Results cached in the translations table keyed by source-text hash
(the text itself derived via ``normalize.sentence_text``, §7.1).
httpx only; the DB connection is injected (module default wired at
app startup), so the logic stays unit-testable.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from app import db, i18n
from app.services import llm, normalize, prompts

GTX_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
GTX_TIMEOUT_S = 6.0

#: sentences per LLM batch call (design §7.2: ~20 keeps a reply inside
#: max_tokens=4096's natural constraint)
TRANSLATE_BATCH_SIZE = 20


class TranslateError(Exception):
    """All translation channels failed."""


_conn = None  # wired by app startup


def configure(conn) -> None:
    global _conn
    _conn = conn


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lookup(conn, text: str) -> str | None:
    if conn is None:
        return None
    row = conn.execute(
        "SELECT dst FROM translations WHERE hash=?", (_hash(text),)
    ).fetchone()
    return row["dst"] if row else None


def _store(conn, text: str, dst: str) -> None:
    if conn is None:
        return
    with db._write_lock:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO translations(hash,src,dst,created_at)"
                " VALUES(?,?,?,?)",
                (_hash(text), text, dst,
                 datetime.now(timezone.utc).isoformat()),
            )


async def _gtx(client: httpx.AsyncClient, text: str) -> str:
    resp = await client.get(
        GTX_URL,
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text},
    )
    resp.raise_for_status()
    data = resp.json()
    parts = [
        seg[0] for seg in (data[0] or []) if seg and seg[0]
    ]
    result = "".join(parts).strip()
    if not result:
        raise ValueError(i18n.t("translate.gtx_empty"))
    return result


async def _mymemory(client: httpx.AsyncClient, text: str) -> str:
    resp = await client.get(
        MYMEMORY_URL, params={"q": text, "langpair": "en|zh-CN"}
    )
    resp.raise_for_status()
    data = resp.json()
    result = (data.get("responseData") or {}).get("translatedText") or ""
    if not result or "MYMEMORY WARNING" in result.upper():
        raise ValueError(i18n.t("translate.mymemory_empty"))
    return result


async def translate(
    text: str,
    llm_cfg=None,
    conn=None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Translate one English sentence to Chinese with cache + fallbacks."""
    text = (text or "").strip()
    if not text:
        return ""
    conn = conn or _conn

    cached = _lookup(conn, text)
    if cached:
        return cached

    own = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=GTX_TIMEOUT_S)
    try:
        for channel in (_gtx, _mymemory):
            try:
                dst = await channel(client, text)
            except Exception:
                continue
            _store(conn, text, dst)
            return dst

        if llm_cfg:
            try:
                obj = await llm.chat_json(
                    llm_cfg,
                    [
                        {"role": "system", "content": i18n.t("translate.system")},
                        {
                            "role": "user",
                            "content": i18n.t("translate.user", text=text),
                        },
                    ],
                )
                dst = (obj.get("translation") or "").strip()
                if dst:
                    _store(conn, text, dst)
                    return dst
            except Exception:
                pass
        raise TranslateError(i18n.t("translate.all_failed"))
    finally:
        if own:
            await client.aclose()


async def translate_sentence(
    words_json: list[dict],
    start: int,
    end: int,
    llm_cfg=None,
    conn=None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Translate one sentence given as a closed word-index range (§7.1).

    Both the cache key and the request text derive from the single
    authoritative ``normalize.sentence_text`` (space join, no
    punctuation), so every historical derivation style hits the same
    ``translations`` row instead of missing itself.
    """
    text = normalize.sentence_text(words_json, start, end)
    return await translate(text, llm_cfg=llm_cfg, conn=conn, client=client)


def lookup_cached(conn, text: str) -> str | None:
    """Public translations-cache read (the pipeline's §7.2 pre-check:
    a sentence already translated for another material is reused and
    never sent to the LLM again)."""
    return _lookup(conn, text)


async def translate_llm_batch(
    conn,
    cfg,
    sentences: list[tuple[int, str]],
    *,
    locale: str = "zh",
    client=None,
) -> dict[int, str]:
    """LLM-first numbered-sentence batch translation (design §7.2).

    ``sentences`` are ``(sentence_index, text)`` pairs whose text the
    CALLER already derived via ``normalize.sentence_text`` (§7.1). The
    list is split into ``TRANSLATE_BATCH_SIZE`` chunks and each chunk is
    ONE ``llm.cached_chat_json`` call (task=``translate``) over the
    ``translate.batch`` prompt, replying ``{"items": [{"i": int,
    "t": str}]}``. Sentences the model omitted -- or answered with junk
    (unknown ``i``, blank ``t``, non-dict item) -- are simply absent
    from the returned dict; the caller decides the fallback. Any chunk
    failure raises :class:`llm.LlmError` (caller decides the fallback).

    ``locale`` only picks the prompt template's language. The
    ``translate.batch`` registry entry is deliberately locale-less
    (§7.4): the output is Simplified Chinese for every locale.
    """
    out: dict[int, str] = {}
    for i in range(0, len(sentences), TRANSLATE_BATCH_SIZE):
        chunk = sentences[i : i + TRANSLATE_BATCH_SIZE]
        numbered = "\n".join(f"{idx}. {text}" for idx, text in chunk)
        messages = [
            {"role": "system", "content": i18n.t("translate.system")},
            {
                "role": "user",
                "content": prompts.render_prompt(
                    conn, "translate.batch", locale, sentences=numbered
                ),
            },
        ]
        obj, _usage, _from_cache = await llm.cached_chat_json(
            conn, cfg, messages, task="translate", client=client,
        )
        wanted = {idx for idx, _ in chunk}
        for item in obj.get("items") or []:
            if not isinstance(item, dict):
                continue
            idx = item.get("i")
            text = str(item.get("t") or "").strip()
            if (
                isinstance(idx, int)
                and not isinstance(idx, bool)
                and idx in wanted
                and text
            ):
                out[idx] = text
    return out
