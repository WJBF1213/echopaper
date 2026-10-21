"""Task B11 tests: sentence translation with cache + fallbacks."""
import json

import httpx
import pytest

from app.services import translate_svc
from app.services.translate_svc import TranslateError, translate


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

    async def get(self, url, **kw):
        self.calls.append(url)
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

    async def fake_chat(cfg, system, user, schema, client=None):
        return {"translation": "LLM译文"}

    monkeypatch.setattr(llm_mod, "chat_json", fake_chat)
    out = await translate("hello", {"provider": "zhipu", "api_key": "k"},
                          conn=tmp_db, client=client)
    assert out == "LLM译文"
