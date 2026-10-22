"""Task B11 tests: sentence translation with cache + fallbacks."""
import json

import httpx
import pytest

from app.services import translate_svc
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
