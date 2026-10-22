"""API tests for the blocks-based paper endpoints (design §5.2)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import ChatUsage


class _FakeEngineManager:
    def configure(self, **kw):
        pass

    async def switch(self, name):
        return {"ok": True}

    async def load(self):
        return {"ok": True}

    async def unload(self):
        return {"unloaded": True}

    def status(self):
        return {"engine": "faster_whisper", "detail": None}


@pytest.fixture
def client(tmp_db, tmp_path):
    app = create_app(
        conn=tmp_db,
        data_dir=tmp_path,
        dist_dir=tmp_path / "missing_dist",
        engine_manager=_FakeEngineManager(),
    )
    return TestClient(app)


# Doubled to 106 words so the completion min_words floor (80) passes.
_SEED_TEXTS = [
    "Good morning I would like to ask about the deposit for the flat.",
    "The deposit is two hundred and fifty pounds in total.",
    "You will need to provide a passport and a bank statement.",
    "The flat is available from the first of September.",
    "There is a bus stop just outside the building.",
] * 2


def _seed(conn, texts=_SEED_TEXTS) -> str:
    """Insert a material built from ``texts``; returns its id."""
    from app.services.jobs import _uid, _now

    words = []
    sentences = []
    for text in texts:
        start = len(words)
        for token in text.split():
            words.append(
                {"w": token, "s": float(len(words)), "e": len(words) + 0.5,
                 "p": 0.95}
            )
        sentences.append([start, len(words) - 1])
    mid = _uid()
    conn.execute(
        "INSERT INTO materials(id,name,source_type,transcript,transcript_source,"
        "words_json,sentences_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (mid, "Exam mat", "upload", "\n".join(texts), "asr",
         json.dumps(words), json.dumps(sentences), _now(), _now()),
    )
    conn.commit()
    return mid


def _passport_item(words, sentences):
    start, end = sentences[2]
    target = "passport".split()
    tokens = [w["w"].lower() for w in words]
    for i in range(start, end - len(target) + 2):
        if tokens[i : i + len(target)] == target:
            return {
                "stem": "You will need to provide a ______ and a bank statement.",
                "i0": i, "i1": i + len(target) - 1,
                "answer": "passport",
                "word_limit": "ONE WORD ONLY",
                "layout": "form",
            }
    raise AssertionError("passport not found")


def test_exam_types_lists_six_key_registry(client):
    res = client.get("/api/exam/types")
    assert res.status_code == 200
    data = res.json()

    types = {t["key"]: t for t in data["types"]}
    assert set(types) == {
        "mcq_single", "mcq_multi", "matching",
        "completion", "short_answer", "map_labelling",
    }
    # Part is no longer an input and part presets are gone (design §4.2).
    assert all("parts" not in t for t in data["types"])
    assert "presets" not in data

    # The six legacy fill-in types survive only as completion's layouts.
    assert types["completion"]["layouts"] == [
        "form", "table", "notes", "sentence", "summary", "flowchart",
    ]
    assert types["completion"]["answer_kind"] == "span"

    # map_labelling generates a scene asset (design §4.3).
    assert types["map_labelling"]["generates_visual"] is True
    assert types["map_labelling"]["answer_kind"] == "matching"

    assert types["mcq_single"]["answer_kind"] == "option"
    assert types["mcq_multi"]["answer_kind"] == "option_multi"
    assert types["matching"]["answer_kind"] == "matching"
    assert types["short_answer"]["answer_kind"] == "span"

    # max_count cap and the deterministic precheck floor (design §4.5).
    assert all(t["max_count"] == 10 for t in data["types"])
    assert types["mcq_single"]["min_words"] == 120
    assert types["mcq_multi"]["min_words"] == 200
    assert types["matching"]["min_words"] == 150
    assert types["completion"]["min_words"] == 80
    assert types["short_answer"]["min_words"] == 80
    assert types["map_labelling"]["min_words"] == 200

    # Names ship in both languages; "name" follows the request locale.
    assert types["completion"]["name_zh"] == "填空题"
    assert types["completion"]["name_en"] == "Completion"
    assert types["completion"]["name"] == "填空题"  # default locale is zh


# ------------------------------------------- POST /materials/{id}/exam


def test_exam_rejects_unknown_type(client, tmp_db):
    mid = _seed(tmp_db)
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "no_such_type", "count": 3}]},
    )
    assert res.status_code == 422
    assert "no_such_type" in res.text


def test_exam_rejects_count_out_of_range(client, tmp_db):
    mid = _seed(tmp_db)
    for bad in (0, 11):
        res = client.post(
            f"/api/materials/{mid}/exam",
            json={"blocks": [{"type": "completion", "count": bad}]},
        )
        assert res.status_code == 422, (bad, res.text)


def test_exam_rejects_empty_and_missing_blocks(client, tmp_db):
    mid = _seed(tmp_db)
    res = client.post(f"/api/materials/{mid}/exam", json={"blocks": []})
    assert res.status_code == 422
    res = client.post(f"/api/materials/{mid}/exam", json={})
    assert res.status_code == 422


def test_exam_rejects_bad_layout_hint(client, tmp_db):
    mid = _seed(tmp_db)
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}],
              "layout_hint": "spiral"},
    )
    assert res.status_code == 422
    assert "spiral" in res.text


def test_exam_unknown_material_is_404(client, tmp_db):
    res = client.post(
        "/api/materials/missing/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    )
    assert res.status_code == 404


def test_exam_requires_llm_key(client, tmp_db):
    mid = _seed(tmp_db)
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    )
    assert res.status_code == 400
    assert "key" in res.json()["detail"].lower() or "llm" in res.json()["detail"].lower()


def test_exam_generates_paper_with_stub_llm(client, tmp_db, monkeypatch):
    mid = _seed(tmp_db)
    row = tmp_db.execute(
        "SELECT words_json, sentences_json FROM materials WHERE id=?", (mid,)
    ).fetchone()
    words = json.loads(row["words_json"])
    sentences = json.loads(row["sentences_json"])

    # Pretend a key is configured.
    monkeypatch.setattr(
        "app.routers.exam.llm_cfg_or_none", lambda _s: {"api_key": "test"}
    )

    from app.services import exam_gen

    async def fake_cached(conn, cfg, messages, *, task, **kwargs):
        assert task == "exam:completion"
        return (
            {"groups": [{"title": "Housing", "items": [_passport_item(words, sentences)]}]},
            ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0),
            False,
        )

    monkeypatch.setattr(
        "app.services.exam_gen.llm.cached_chat_json", fake_cached, raising=False
    )

    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    # Task 10 shape: {paper, skipped}; paper_id arrives with persistence
    # (Task 14).
    assert set(data) == {"paper", "skipped"}
    assert data["skipped"] == []
    paper = data["paper"]
    assert paper["material_id"] == mid
    assert paper["total_items"] == 1
    item = paper["groups"][0]["items"][0]
    assert item["stem"].count("______") == 1
    assert item["word_limit"] == "ONE WORD ONLY"
    assert item["layout"] == "form"
    # Group instruction synthesized from the items (design §4.1).
    assert paper["groups"][0]["instruction"] == (
        "Complete the form below. Write ONE WORD ONLY for each answer."
    )
    assert "part" not in paper and "preset" not in paper

    # layout_hint forces every item's layout; regenerate rides along and
    # still succeeds (the marker only changes the prompt/cache key).
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={
            "blocks": [{"type": "completion", "count": 1}],
            "layout_hint": "notes",
            "regenerate": True,
        },
    )
    assert res.status_code == 200, res.text
    paper = res.json()["paper"]
    assert paper["groups"][0]["items"][0]["layout"] == "notes"
    assert paper["groups"][0]["instruction"].startswith(
        "Complete the notes below."
    )
    _ = exam_gen


# ------------------------------- suitability refusal (design §4.5)


def test_exam_all_refused_by_precheck_returns_400(client, tmp_db, monkeypatch):
    """Every block refused -> 400 with body {"detail": {"skipped": [...]}}
    listing each refused type with its reason; no LLM call is spent."""
    mid = _seed(tmp_db)  # 104 words: under mcq_single's 120-word floor
    monkeypatch.setattr(
        "app.routers.exam.llm_cfg_or_none", lambda _s: {"api_key": "test"}
    )
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "mcq_single", "count": 2}]},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert set(detail) == {"skipped"}
    assert len(detail["skipped"]) == 1
    assert detail["skipped"][0]["type"] == "mcq_single"
    assert detail["skipped"][0]["reason"].startswith("[precheck]")


def test_exam_all_refused_by_llm_returns_400(client, tmp_db, monkeypatch):
    """A refused LLM response for the only block is also an all-refused
    request: 400 with the skipped body (one LLM call, no retry)."""
    mid = _seed(tmp_db)
    monkeypatch.setattr(
        "app.routers.exam.llm_cfg_or_none", lambda _s: {"api_key": "test"}
    )

    async def refuse(conn, cfg, messages, *, task, **kwargs):
        return (
            {"refused": True, "reason": "转写没有足够的事实支撑出题"},
            ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0),
            False,
        )

    monkeypatch.setattr(
        "app.services.exam_gen.llm.cached_chat_json", refuse, raising=False
    )
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["skipped"] == [
        {"type": "completion", "reason": "转写没有足够的事实支撑出题"}
    ]


def test_exam_mixed_refusal_returns_200_with_skipped(client, tmp_db, monkeypatch):
    """Partial refusal -> 200: the paper keeps the successful group and
    the response lists the refused type with its reason."""
    mid = _seed(tmp_db)
    row = tmp_db.execute(
        "SELECT words_json, sentences_json FROM materials WHERE id=?", (mid,)
    ).fetchone()
    words = json.loads(row["words_json"])
    sentences = json.loads(row["sentences_json"])
    monkeypatch.setattr(
        "app.routers.exam.llm_cfg_or_none", lambda _s: {"api_key": "test"}
    )

    async def fake_cached(conn, cfg, messages, *, task, **kwargs):
        assert task == "exam:completion"
        return (
            {"groups": [{"title": "Housing",
                         "items": [_passport_item(words, sentences)]}]},
            ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0),
            False,
        )

    monkeypatch.setattr(
        "app.services.exam_gen.llm.cached_chat_json", fake_cached, raising=False
    )
    # completion succeeds; mcq_single is precheck-refused (104 < 120 words).
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1},
                         {"type": "mcq_single", "count": 2}]},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert set(data) == {"paper", "skipped"}
    assert data["paper"]["total_items"] == 1
    assert [g["type"] for g in data["paper"]["groups"]] == ["completion"]
    assert len(data["skipped"]) == 1
    assert data["skipped"][0]["type"] == "mcq_single"
    assert data["skipped"][0]["reason"].startswith("[precheck]")


def test_exam_shortfall_group_partial_flag(client, tmp_db, monkeypatch):
    """Insufficiency is not refusal: an under-quota block returns 200 with
    its group marked partial and an empty skipped list."""
    # 156 words: clears matching's 150-word floor.
    mid = _seed(tmp_db, _SEED_TEXTS * 3)
    row = tmp_db.execute(
        "SELECT words_json, sentences_json FROM materials WHERE id=?", (mid,)
    ).fetchone()
    words = json.loads(row["words_json"])
    monkeypatch.setattr(
        "app.routers.exam.llm_cfg_or_none", lambda _s: {"api_key": "test"}
    )

    def _span(text):
        target = text.lower().split()
        tokens = [w["w"].lower() for w in words]
        for i in range(len(tokens) - len(target) + 1):
            if tokens[i: i + len(target)] == target:
                return i, i + len(target) - 1
        raise AssertionError(f"span not found: {text}")

    two_hundred = _span("two hundred")
    passport = _span("passport")
    response = {"groups": [{"title": "Housing", "options": [
        "Deposit amount", "ID document", "Start month", "Bus route",
    ], "items": [
        {"stem": "How much is due?", "answer": "A",
         "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}]},
        {"stem": "What must you hand over?", "answer": "B",
         "evidence": [{"i0": passport[0], "i1": passport[1]}]},
    ]}]}

    async def fake_cached(conn, cfg, messages, *, task, **kwargs):
        assert task == "exam:matching"
        return (
            response,
            ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0),
            False,
        )

    monkeypatch.setattr(
        "app.services.exam_gen.llm.cached_chat_json", fake_cached, raising=False
    )
    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "matching", "count": 3}]},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["skipped"] == []
    group = data["paper"]["groups"][0]
    assert group["type"] == "matching"
    assert len(group["items"]) == 2
    assert group["partial"] is True
