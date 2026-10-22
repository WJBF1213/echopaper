"""Sentence translation service (Task B11): gtx -> MyMemory -> LLM.

Results cached in the translations table keyed by source-text hash.
httpx only; the DB connection is injected (module default wired at
app startup), so the logic stays unit-testable.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from app import db, i18n
from app.services import llm, normalize

GTX_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
GTX_TIMEOUT_S = 6.0


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
