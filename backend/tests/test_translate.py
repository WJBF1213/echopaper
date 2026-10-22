"""Task B11 tests: sentence translation with cache + fallbacks.

Extended for the redesign §7.2 pipeline: ``translate_llm_batch`` is the
LLM-first numbered-sentence batch channel (ONE ``cached_chat_json`` call
per ~20-sentence batch, task=``translate``); per-sentence channels stay
the fallback. All LLM/net access is faked.
"""
import json
import re
from types import SimpleNamespace

import httpx
import pytest

from app.services import llm as llm_mod
from app.services import translate_svc
from app.services.llm import LlmError
from app.services.translate_svc import TranslateError, translate, translate_sentence


class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)  # each: FakeResp | Exception; routed by call order
        self.calls = []
        self.calls_kw = []  # kwargs of each get(), for request-text checks

    async def get(self, url, **kw):
        self.calls.append(url)
        self.calls_kw.append(kw)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        pass


GTX_OK = FakeResp([[["你好", "hello", None, None, 10]], None, "en", None,
                   None, None, 1.0, None, [""], None, None, [1]])
MYMEMORY_OK = FakeResp({"responseData": {"translatedText": "你好"},
                        "responseStatus": 200})


@pytest.mark.asyncio
async def test_cache_hit_no_network(tmp_db):
    from app.services.translate_svc import _hash, _store

    _store(tmp_db, "hello", "你好缓存")
    client = FakeClient([])
    out = await translate("hello", None, conn=tmp_db, client=client)
    assert out == "你好缓存"
    assert client.calls == []


@pytest.mark.asyncio
async def test_gtx_fail_mymemory_ok(tmp_db):
    client = FakeClient([httpx.ConnectError("gtx down"), MYMEMORY_OK])
    out = await translate("hello", None, conn=tmp_db, client=client)
    assert out == "你好"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_all_fail_raises(tmp_db):
    client = FakeClient([
        httpx.ConnectError("down1"),
        httpx.ConnectError("down2"),
    ])
    with pytest.raises(TranslateError):
        await translate("hello", None, conn=tmp_db, client=client)


@pytest.mark.asyncio
async def test_result_cached(tmp_db):
    client = FakeClient([GTX_OK])
    out = await translate("hello", None, conn=tmp_db, client=client)
    assert out == "你好"
    row = tmp_db.execute(
        "SELECT src,dst FROM translations WHERE hash=?",
        (translate_svc._hash("hello"),),
    ).fetchone()
    assert row["src"] == "hello" and row["dst"] == "你好"
    # second call served from cache, no network
    client2 = FakeClient([])
    out2 = await translate("hello", None, conn=tmp_db, client=client2)
    assert out2 == "你好"
    assert client2.calls == []


@pytest.mark.asyncio
async def test_llm_fallback_used(tmp_db, monkeypatch):
    from app.services import llm as llm_mod

    client = FakeClient([httpx.ConnectError("gtx down"),
                         httpx.ConnectError("mymemory down")])

    async def fake_chat(cfg, messages, **kwargs):
        return {"translation": "LLM译文"}

    monkeypatch.setattr(llm_mod, "chat_json", fake_chat)
    out = await translate("hello", {"provider": "zhipu", "api_key": "k"},
                          conn=tmp_db, client=client)
    assert out == "LLM译文"


# --------------------------------------- translate_sentence (spec §7.1)

WORDS = [
    {"w": "Hello", "s": 0.0, "e": 0.2},
    {"w": "there", "s": 0.2, "e": 0.4},
    {"w": "friend", "s": 0.4, "e": 0.6},
]


@pytest.mark.asyncio
async def test_translate_sentence_one_cache_key_regardless_of_legacy_style(tmp_db):
    """Spec §7.1: same words_json + range -> exactly ONE translations row.

    Historically the same sentence was derived three ways (plain join /
    period-appended / another join) so the cache missed itself. All
    derivation styles now funnel through normalize.sentence_text, so
    repeated translation of the same range hits the same single row.
    """
    from app.services.normalize import sentence_text

    client = FakeClient([GTX_OK])
    out = await translate_sentence(WORDS, 0, 2, None,
                                   conn=tmp_db, client=client)
    assert out == "你好"

    # stored under the authoritative derivation's key -- no period appended
    key = translate_svc._hash(sentence_text(WORDS, 0, 2))
    row = tmp_db.execute(
        "SELECT src,dst FROM translations WHERE hash=?", (key,)
    ).fetchone()
    assert row is not None
    assert row["src"] == "Hello there friend"

    # every later call (any historical caller, now routed through
    # sentence_text) is a cache hit: no network, still exactly one row
    client2 = FakeClient([])
    out2 = await translate_sentence(WORDS, 0, 2, None,
                                    conn=tmp_db, client=client2)
    assert out2 == "你好"
    assert client2.calls == []
    n = tmp_db.execute("SELECT COUNT(*) AS c FROM translations").fetchone()
    assert n["c"] == 1


@pytest.mark.asyncio
async def test_translate_sentence_request_text_is_authoritative(tmp_db):
    """The request text sent to channels is the sentence_text derivation."""
    client = FakeClient([GTX_OK])
    await translate_sentence(WORDS, 0, 2, None, conn=tmp_db, client=client)
    sent = client.calls_kw[0]["params"]["q"]
    assert sent == "Hello there friend"  # space join, no trailing period


@pytest.mark.asyncio
async def test_translate_sentence_one_word_range(tmp_db):
    """1-word sentence boundary: [i, i] translates exactly that word."""
    _store = translate_svc._store
    _store(tmp_db, "Thanks", "谢谢")
    client = FakeClient([])
    words = [{"w": "Thanks", "s": 0.0, "e": 0.3}]
    out = await translate_sentence(words, 0, 0, None,
                                   conn=tmp_db, client=client)
    assert out == "谢谢"
    assert client.calls == []


@pytest.mark.asyncio
async def test_translate_sentence_empty_derivation_skips_network(tmp_db):
    """An empty derived text returns "" without any channel call."""
    client = FakeClient([])
    words = [{"w": "", "s": 0.0, "e": 0.1}]
    out = await translate_sentence(words, 0, 0, None,
                                   conn=tmp_db, client=client)
    assert out == ""
    assert client.calls == []


def test_legacy_derivation_styles_agree_with_authoritative():
    """exam_gen/pos legacy inline joins equal normalize.sentence_text."""
    from app.services.exam_gen import _sentence_text as exam_join
    from app.services.normalize import sentence_text

    plain = [w["w"] for w in WORDS]
    # legacy exam_gen style: " ".join(words[s:e+1]).strip()
    assert exam_join(plain, 0, 2) == sentence_text(WORDS, 0, 2)
    # legacy pos._formulaic_words inline style
    assert " ".join(plain[0 : 2 + 1]).strip() == sentence_text(WORDS, 0, 2)


# ------------------------------------------- translate_llm_batch (spec §7.2)

LLM_CFG = {"provider": "zhipu", "api_key": "k"}


class FakeChat:
    """Fake llm.cached_chat_json honouring its contract:
    (conn, cfg, messages, *, task, ...) -> (obj, usage, from_cache).
    Replies route by call order; each is a parsed dict or an Exception."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def __call__(self, conn, cfg, messages, *, task, **kwargs):
        self.calls.append(
            {"conn": conn, "cfg": cfg, "messages": messages,
             "task": task, "kwargs": kwargs}
        )
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, SimpleNamespace(
            prompt_tokens=1, completion_tokens=1, cached_tokens=0
        ), False


@pytest.mark.asyncio
async def test_llm_batch_one_call_translates_many_sentences(tmp_db, monkeypatch):
    """§7.2 LLM 优先、批量: a whole numbered batch is ONE cached_chat_json
    call with task=translate; the reply's items map back i -> t."""
    sentences = [
        (0, "Hello there friend"),
        (1, "The castle stands"),
        (2, "A quiet village sits"),
    ]
    chat = FakeChat([{"items": [
        {"i": 0, "t": "你好，朋友"},
        {"i": 1, "t": "城堡矗立"},
        {"i": 2, "t": "一个安静的村庄"},
    ]}])
    monkeypatch.setattr(llm_mod, "cached_chat_json", chat)
    out = await translate_svc.translate_llm_batch(tmp_db, LLM_CFG, sentences)
    assert out == {0: "你好，朋友", 1: "城堡矗立", 2: "一个安静的村庄"}
    # exactly one LLM round trip for the whole batch
    assert len(chat.calls) == 1
    call = chat.calls[0]
    assert call["task"] == "translate"
    assert call["conn"] is tmp_db and call["cfg"] is LLM_CFG
    assert call["messages"][0]["role"] == "system"
    user = call["messages"][-1]["content"]
    # sentences arrive numbered by their sentence_index
    assert "0. Hello there friend" in user
    assert "1. The castle stands" in user
    assert "2. A quiet village sits" in user
    # the prompt itself instructs the JSON-only reply shape
    assert '{"items"' in user


@pytest.mark.asyncio
async def test_llm_batch_chunks_at_twenty_sentences(tmp_db, monkeypatch):
    """~20 句/批 (max_tokens=4096 natural constraint): 21 sentences make
    exactly two calls, numbering preserved across chunks."""
    sentences = [(i, f"Sentence number {i}") for i in range(21)]
    calls = []

    async def echo_chat(conn, cfg, messages, *, task, **kwargs):
        calls.append(messages)
        nums = [
            int(m)
            for m in re.findall(r"^(\d+)\. ", messages[-1]["content"], re.M)
        ]
        return (
            {"items": [{"i": n, "t": f"译文{n}"} for n in nums]},
            SimpleNamespace(prompt_tokens=1, completion_tokens=1,
                            cached_tokens=0),
            False,
        )

    monkeypatch.setattr(llm_mod, "cached_chat_json", echo_chat)
    out = await translate_svc.translate_llm_batch(tmp_db, LLM_CFG, sentences)
    assert out == {i: f"译文{i}" for i in range(21)}
    assert len(calls) == 2
    assert "20. Sentence number 20" in calls[1][-1]["content"]
    assert "0. Sentence number 0" not in calls[1][-1]["content"]


@pytest.mark.asyncio
async def test_llm_batch_partial_missing_indices_absent(tmp_db, monkeypatch):
    """Partial results are kept; junk items (unknown i, blank t, non-dict,
    missing i) are dropped instead of crashing the caller."""
    chat = FakeChat([{"items": [
        {"i": 0, "t": "只翻第一句"},
        {"i": 7, "t": "编号不在本批"},
        {"i": 1, "t": "   "},
        "junk",
        {"t": "没有编号"},
    ]}])
    monkeypatch.setattr(llm_mod, "cached_chat_json", chat)
    out = await translate_svc.translate_llm_batch(
        tmp_db, LLM_CFG, [(0, "A sentence"), (1, "Another one")]
    )
    assert out == {0: "只翻第一句"}


@pytest.mark.asyncio
async def test_llm_batch_llm_error_raises(tmp_db, monkeypatch):
    """LlmError propagates: the CALLER decides the fallback semantics."""
    chat = FakeChat([LlmError("provider down")])
    monkeypatch.setattr(llm_mod, "cached_chat_json", chat)
    with pytest.raises(LlmError):
        await translate_svc.translate_llm_batch(
            tmp_db, LLM_CFG, [(0, "A sentence")]
        )


@pytest.mark.asyncio
async def test_llm_batch_locale_parameter_rendered_for_any_locale(tmp_db, monkeypatch):
    """translate.batch is one locale-less registry entry (§7.4: the
    output is Chinese regardless of UI locale): both locale values
    render the same prompt."""
    seen = []

    async def echo_chat(conn, cfg, messages, *, task, **kwargs):
        seen.append(messages[-1]["content"])
        return {"items": []}, None, False

    monkeypatch.setattr(llm_mod, "cached_chat_json", echo_chat)
    for loc in ("zh", "en"):
        await translate_svc.translate_llm_batch(
            tmp_db, LLM_CFG, [(0, "A sentence")], locale=loc
        )
    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert "0. A sentence" in seen[0]
