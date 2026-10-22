"""API tests for the experimental full-paper endpoint."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import exam_gen
from app.services.exam_presets import PRESETS


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


def _seed(conn) -> str:
    from app.services.jobs import _uid, _now

    words = []
    sentences = []
    texts = [
        "Good morning I would like to ask about the deposit for the flat.",
        "The deposit is two hundred and fifty pounds in total.",
        "You will need to provide a passport and a bank statement.",
        "The flat is available from the first of September.",
        "There is a bus stop just outside the building.",
    ]
    for text in texts:
        start = len(words)
        for token in text.split():
            words.append({"w": token, "s": float(len(words)), "e": len(words) + 0.5, "p": 0.95})
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


def _answer_item(words, sentence, answer, stem):
    start, end = sentence
    target = answer.lower().split()
    tokens = [w["w"].lower() for w in words]
    for i in range(start, end - len(target) + 2):
        if tokens[i : i + len(target)] == target:
            return {"stem": stem, "i0": i, "i1": i + len(target) - 1, "answer": answer}
    raise AssertionError(answer)


def test_exam_types_lists_types_and_presets(client):
    res = client.get("/api/exam/types")
    assert res.status_code == 200
    data = res.json()
    keys = {t["key"] for t in data["types"]}
    assert {"form_completion", "note_completion", "mcq_single", "matching"} <= keys
    assert {p["key"] for p in data["presets"]} >= {"p1_form", "p4_notes"}
    visual = next(t for t in data["types"] if t["key"] == "map_labelling")
    assert visual["needs_visual"] is True


def test_exam_rejects_preset_for_wrong_part(client, tmp_db):
    mid = _seed(tmp_db)
    res = client.post(
        f"/api/materials/{mid}/exam", json={"part": 4, "preset": "p1_form"}
    )
    assert res.status_code == 400
    assert "part 1" in res.json()["detail"]


def test_exam_requires_llm_key(client, tmp_db):
    mid = _seed(tmp_db)
    res = client.post(f"/api/materials/{mid}/exam", json={"part": 1})
    assert res.status_code == 400
    assert "key" in res.json()["detail"].lower() or "LLM" in res.json()["detail"]


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

    from app.services import jobs as jobs_svc
    from app.services.llm import LlmError

    async def fake_chat(cfg, system, user, schema):
        # One valid item from the first content sentence.
        return {
            "groups": [
                {
                    "title": "Housing",
                    "items": [
                        _answer_item(
                            words,
                            sentences[0],
                            "deposit",
                            "I would like to ask about the ______ for the flat.",
                        )
                    ],
                }
            ]
        }

    monkeypatch.setattr(exam_gen.llm, "chat_json", fake_chat)
    # The router imports llm lazily inside generate_paper, so patch the module
    # attribute used by the generator.
    monkeypatch.setattr(
        "app.services.exam_gen.llm.chat_json", fake_chat, raising=False
    )

    res = client.post(f"/api/materials/{mid}/exam", json={"part": 1, "preset": "p1_form"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["part"] == 1
    assert data["preset"] == "p1_form"
    assert data["total_items"] >= 1
    assert data["groups"][0]["items"][0]["stem"].count("______") == 1
    assert data["available_presets"]
    _ = jobs_svc, LlmError
