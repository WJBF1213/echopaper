"""Sentence translation service: gtx -> MyMemory -> LLM, plus the
redesign §7.2 LLM-first batch channel ``translate_llm_batch`` and the
shared snapshot stage ``translate_material_sentences`` used by the
ingestion pipeline AND the transcript re-edit endpoint (the
per-sentence channels remain the fallback).

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


async def translate_material_sentences(
    conn,
    cfg,
    material_id: str,
    words: list[dict],
    sents: list[list[int]],
    *,
    on_progress=None,
) -> int:
    """(Re)generate the material_translations snapshot (§7.2 stage body).

    Shared by the ingestion pipeline (jobs) and the transcript re-edit
    endpoint: src text derives from the single authoritative §7.1
    function, sentences already in the shared cache skip the LLM
    entirely, the LLM batch runs first and the per-sentence channels
    (gtx -> MyMemory -> LLM) catch whatever it missed; a sentence
    failing every channel is simply absent from the snapshot (the
    listen view shows its placeholder). Results land in
    material_translations and are written back to the shared
    translations cache for cross-material dedup. ``on_progress(done,
    total)`` fires after each pending chunk. Returns the snapshot row
    count written.
    """
    all_pairs: list[tuple[int, str]] = []  # every non-empty sentence
    pending: list[tuple[int, str]] = []    # not in the shared cache
    results: dict[int, str] = {}
    for idx, (s, e) in enumerate(sents):
        text = normalize.sentence_text(words, s, e)
        if not text:
            continue
        all_pairs.append((idx, text))
        cached = lookup_cached(conn, text)
        if cached is not None:
            results[idx] = cached
        else:
            pending.append((idx, text))
    if not all_pairs:
        return 0

    total = len(pending)
    for i in range(0, total, TRANSLATE_BATCH_SIZE):
        chunk = pending[i : i + TRANSLATE_BATCH_SIZE]
        try:
            got = await translate_llm_batch(conn, cfg, chunk)
        except Exception:  # noqa: BLE001 - any translation trouble
            # (LlmError, an httpx status from a bad key, a broken prompt
            # override) degrades to the per-sentence channels instead of
            # failing the caller (§7.2: translation never kills it).
            got = {}
        for idx, text in chunk:
            if idx in got:
                continue
            try:
                got[idx] = await translate(text, llm_cfg=cfg, conn=conn)
            except Exception:  # noqa: BLE001 - TranslateError (every
                # channel down) or an unexpected transport failure: the
                # sentence just stays untranslated (no snapshot row).
                continue
        results.update(got)
        if on_progress is not None:
            on_progress(min(i + TRANSLATE_BATCH_SIZE, total), total)

    stamp = datetime.now(timezone.utc).isoformat()
    snap_rows = []
    cache_rows = []
    for idx, text in all_pairs:
        dst = results.get(idx)
        if not dst:
            continue
        snap_rows.append((material_id, idx, text, dst, stamp))
        cache_rows.append((_hash(text), text, dst, stamp))
    if snap_rows:
        with db._write_lock:
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO material_translations"
                    "(material_id,sentence_index,src,dst,created_at)"
                    " VALUES(?,?,?,?,?)",
                    snap_rows,
                )
                # writeback to the shared cache: 同句同译 across
                # materials (§7.2)
                conn.executemany(
                    "INSERT OR REPLACE INTO translations"
                    "(hash,src,dst,created_at) VALUES(?,?,?,?)",
                    cache_rows,
                )
    return len(snap_rows)
