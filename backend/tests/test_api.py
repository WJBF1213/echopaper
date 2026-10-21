"""Task B12 tests: REST API routes, audio Range, static hosting."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeEngineManager:
    def __init__(self):
        self.switched = []
        self.unloaded = 0

    def configure(self, **kw):
        pass

    async def acquire(self):
        return self

    async def release(self):
        pass

    async def unload_now(self):
        self.unloaded += 1
        return {"state": "unloaded", "engine": "parakeet", "model": "m",
                "idle_unload_min": 10}

    async def switch(self, name):
        self.switched.append(name)
        return {"state": "unloaded", "engine": name, "model": "m",
                "idle_unload_min": 10}

    def status(self):
        return {"state": "unloaded", "engine": "parakeet", "model": "m",
                "idle_unload_min": 10}

    def transcribe(self, path):
        return []


class FakeJobs:
    def __init__(self):
        self.payload = None

    def configure(self, **kw):
        pass

    async def create(self, payload):
        self.payload = payload
        return "job-123"

    def get(self, job_id):
        return {"id": job_id, "state": "done", "percent": 100.0,
                "material_id": "m1"}


@pytest.fixture()
def app(tmp_db, tmp_path):
    eng = FakeEngineManager()
    jobs = FakeJobs()
    application = create_app(
        conn=tmp_db,
        data_dir=tmp_path,
        dist_dir=tmp_path / "missing_dist",
        engine_manager=eng,
        jobs_manager=jobs,
    )
    application.state.test_engine = eng
    application.state.test_jobs = jobs
    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


def _seed_material(conn, name="Mat", words=None, sentences=None, audio=None,
                   source="asr"):
    from app.services.jobs import _uid, _now

    mid = _uid()
    if words is None:
        words = [
            {"w": w, "s": float(i), "e": float(i) + 0.5}
            for i, w in enumerate(
                ["The", "little", "castle", "stands", "near", "the",
                 "river", "The", "tall", "tower", "rises", "above", "the",
                 "trees", "A", "quiet", "village", "sits", "beside", "the",
                 "lake"]
            )
        ]
    if sentences is None:
        sentences = [[0, 6], [7, 13], [14, 20]]
    conn.execute(
        "INSERT INTO materials(id,name,source_type,audio_path,audio_url,"
        "duration_s,transcript,transcript_source,words_json,sentences_json,"
        "asr_model,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, name, "upload", audio, None, 21.0,
         "The little castle stands near the river.", source,
         json.dumps(words), json.dumps(sentences), "fake",
         _now(), _now()),
    )
    return mid


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["version"]


def test_static_missing_dist_graceful(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "hint" in r.json()


def test_create_material_job_flow(app, client, tmp_path):
    r = client.post(
        "/api/materials",
        data={"name": "New", "mode": "nouns", "blank_count": "5"},
        files={"audio": ("a.mp3", b"ID3-bytes", "audio/mpeg")},
    )
    assert r.status_code == 200
    assert r.json() == {"job_id": "job-123"}
    payload = app.state.test_jobs.payload
    assert payload["name"] == "New"
    assert payload["audio_bytes"] == b"ID3-bytes"
    assert payload["mode"] == "nouns"
    j = client.get("/api/jobs/job-123").json()
    assert j["state"] == "done" and j["material_id"] == "m1"


def test_create_material_requires_source(client):
    r = client.post("/api/materials", data={"name": "Empty"})
    assert r.status_code == 400


def test_materials_list_with_stats(tmp_db, client):
    mid = _seed_material(tmp_db)
    # one attempt 8/10 -> best score 0.8
    from app.services.jobs import _uid, _now

    sid = _uid()
    tmp_db.execute(
        "INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,"
        "stale,created_at) VALUES(?,?, 'nouns',10,'{}',0,?)", (sid, mid, _now()))
    aid = _uid()
    tmp_db.execute(
        "INSERT INTO attempts(id,set_id,material_id,mode,started_at,finished_at,"
        "ok,total,duration_s) VALUES(?,?,?,?,?,?,?,?,?)",
        (aid, sid, mid, "nouns", _now(), "2026-10-21T10:00:00", 8, 10, 60.0))
    r = client.get("/api/materials")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == mid
    assert items[0]["sets_count"] == 1
    assert abs(items[0]["best_score"] - 0.8) < 1e-9
    assert items[0]["last_practice"] == "2026-10-21T10:00:00"


def test_material_detail(tmp_db, client):
    mid = _seed_material(tmp_db)
    r = client.get(f"/api/materials/{mid}")
    assert r.status_code == 200
    body = r.json()
    assert body["words"][0]["w"] == "The"
    assert body["sentences"][0] == [0, 6]
    assert isinstance(body["sets"], list)
    r404 = client.get("/api/materials/nope")
    assert r404.status_code == 404


def test_audio_range_206(tmp_db, client, tmp_path):
    audio = tmp_path / "aud.mp3"
    audio.write_bytes(b"ABC")  # 3 bytes
    mid = _seed_material(tmp_db, audio=str(audio))
    r = client.get(f"/api/materials/{mid}/audio",
                   headers={"Range": "bytes=1-1"})
    assert r.status_code == 206
    assert r.content == b"B"
    assert r.headers["content-range"] == "bytes 1-1/3"
    assert r.headers["accept-ranges"] == "bytes"
    # full request -> 200
    r2 = client.get(f"/api/materials/{mid}/audio")
    assert r2.status_code == 200 and r2.content == b"ABC"


def test_audio_missing_404(tmp_db, client):
    mid = _seed_material(tmp_db, audio=None)
    assert client.get(f"/api/materials/{mid}/audio").status_code == 404


def test_put_transcript_marks_stale_and_realigns(tmp_db, client):
    mid = _seed_material(tmp_db)
    from app.services.jobs import _uid, _now

    sid = _uid()
    tmp_db.execute(
        "INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,"
        "stale,created_at) VALUES(?,?, 'llm',10,'{}',0,?)", (sid, mid, _now()))
    tmp_db.execute(
        "INSERT INTO blanks(id,set_id,position,answer,alternatives_json,"
        "word_start,word_end,t_start,t_end,type,word_limit)"
        " VALUES(?,?,1,'castle','[]',2,2,2.0,2.5,'noun','ONE WORD ONLY')",
        (_uid(), sid))
    r = client.put(f"/api/materials/{mid}/transcript",
                   json={"transcript": "The little castle stands near the river."})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript_source"] == "aligned"
    assert sid in body["stale_sets"]
    stale_row = tmp_db.execute(
        "SELECT stale FROM question_sets WHERE id=?", (sid,)).fetchone()
    assert stale_row["stale"] == 1
    # words re-anchored to official text
    assert body["words"][2]["w"] == "castle"
    # attempts preserved
    assert tmp_db.execute("SELECT COUNT(*) c FROM blanks WHERE set_id=?",
                          (sid,)).fetchone()["c"] == 1


def test_delete_material_cascades(tmp_db, client, tmp_path):
    audio = tmp_path / "del.mp3"
    audio.write_bytes(b"XYZ")
    mid = _seed_material(tmp_db, audio=str(audio))
    from app.services.jobs import _uid, _now

    sid = _uid()
    tmp_db.execute(
        "INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,"
        "stale,created_at) VALUES(?,?, 'nouns',5,'{}',0,?)", (sid, mid, _now()))
    r = client.delete(f"/api/materials/{mid}")
    assert r.status_code == 200
    assert client.get(f"/api/materials/{mid}").status_code == 404
    assert tmp_db.execute(
        "SELECT COUNT(*) c FROM question_sets").fetchone()["c"] == 0
    assert not audio.exists()  # audio file removed


def test_create_set_and_get(tmp_db, client):
    mid = _seed_material(tmp_db)
    r = client.post(f"/api/materials/{mid}/sets",
                    json={"mode": "nouns", "blank_count": 3})
    assert r.status_code == 200
    set_id = r.json()["set_id"]
    g = client.get(f"/api/sets/{set_id}").json()
    assert 1 <= len(g["blanks"]) <= 3
    for b in g["blanks"]:
        assert {"id", "position", "answer", "word_start", "word_end",
                "t_start", "t_end", "type", "word_limit"} <= set(b)


def test_manual_set_with_override(tmp_db, client):
    mid = _seed_material(tmp_db)
    r = client.post(
        f"/api/materials/{mid}/sets",
        json={"mode": "manual", "blank_count": 0,
              "transcript_override": "The [castle] near the [river]."},
    )
    assert r.status_code == 200
    set_id = r.json()["set_id"]
    blanks = client.get(f"/api/sets/{set_id}").json()["blanks"]
    assert sorted(b["answer"] for b in blanks) == ["castle", "river"]


def test_attempt_grading_persisted(tmp_db, client):
    mid = _seed_material(tmp_db)
    from app.services.jobs import _uid, _now

    sid = _uid()
    tmp_db.execute(
        "INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,"
        "stale,created_at) VALUES(?,?, 'nouns',2,'{}',0,?)", (sid, mid, _now()))
    b1, b2 = _uid(), _uid()
    tmp_db.executemany(
        "INSERT INTO blanks(id,set_id,position,answer,alternatives_json,"
        "word_start,word_end,t_start,t_end,type,word_limit)"
        " VALUES(?,?,?,?,'[]',2,2,2.0,2.5,'noun','ONE WORD ONLY')",
        [(b1, sid, 1, "castle"), (b2, sid, 2, "river")])
    r = client.post(f"/api/sets/{sid}/attempts", json={"answers": [
        {"blank_id": b1, "text": "Castle,"},   # correct after normalization
        {"blank_id": b2, "text": "lake"},      # wrong
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] == 1 and body["total"] == 2
    results = {x["blank_id"]: x for x in body["results"]}
    assert results[b1]["correct"] is True
    assert results[b2]["correct"] is False
    # persisted
    row = tmp_db.execute(
        "SELECT * FROM attempts WHERE set_id=?", (sid,)).fetchone()
    assert row["ok"] == 1 and row["total"] == 2
    assert tmp_db.execute(
        "SELECT COUNT(*) c FROM attempt_items").fetchone()["c"] == 2
    # history endpoint
    hist = client.get(f"/api/materials/{mid}/attempts").json()
    assert len(hist) == 1


def test_dictation_attempt(tmp_db, client):
    mid = _seed_material(tmp_db)
    r = client.post(f"/api/materials/{mid}/attempts", json={
        "mode": "dictation",
        "items": [{"word_index": 2, "text": "castle"},
                  {"word_index": 3, "text": "wrong"}],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] == 1 and body["total"] == 2
    assert body["results"][0]["correct"] is True


def test_wrong_words_aggregation(tmp_db, client):
    mid = _seed_material(tmp_db)
    from app.services.jobs import _uid, _now

    sid = _uid()
    tmp_db.execute(
        "INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,"
        "stale,created_at) VALUES(?,?, 'nouns',2,'{}',0,?)", (sid, mid, _now()))
    b1, b2 = _uid(), _uid()
    tmp_db.executemany(
        "INSERT INTO blanks(id,set_id,position,answer,alternatives_json,"
        "word_start,word_end,t_start,t_end,type,word_limit)"
        " VALUES(?,?,?,?,'[]',2,2,2.0,2.5,'noun','ONE WORD ONLY')",
        [(b1, sid, 1, "castle"), (b2, sid, 2, "river")])
    # two attempts, both miss 'castle' once, 'river' missed once
    for _ in range(2):
        r = client.post(f"/api/sets/{sid}/attempts", json={"answers": [
            {"blank_id": b1, "text": "xxx"},
            {"blank_id": b2, "text": "river"},
        ]})
        assert r.status_code == 200
    client.post(f"/api/sets/{sid}/attempts", json={"answers": [
        {"blank_id": b1, "text": "castle"},
        {"blank_id": b2, "text": "yyy"},
    ]})
    r = client.get("/api/review/wrong-words")
    assert r.status_code == 200
    items = r.json()
    by_word = {x["word"]: x for x in items}
    assert by_word["castle"]["times_wrong"] == 2
    assert by_word["river"]["times_wrong"] == 1
    assert by_word["castle"]["material_id"] == mid
    assert by_word["castle"]["t_start"] == 2.0


def test_settings_key_write_only(tmp_db, client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert "api_key" not in json.dumps(body["llm"])
    assert "has_key" in body["llm"]
    # write a key
    r2 = client.put("/api/settings", json={
        "llm": {"provider": "custom", "base_url": "https://x.example/v1",
                "model": "my-model", "api_key": "sk-secret-123"}})
    assert r2.status_code == 200
    g = client.get("/api/settings").json()
    assert g["llm"]["provider"] == "custom"
    assert g["llm"]["base_url"] == "https://x.example/v1"
    assert g["llm"]["has_key"] is True
    assert "sk-secret-123" not in json.dumps(g)
    # stored value kept server-side
    from app import db as db_mod
    stored = db_mod.get_setting(tmp_db, "llm")
    assert stored["api_key"] == "sk-secret-123"


def test_settings_engine_switch_triggers_manager(app, client):
    r = client.put("/api/settings", json={"asr": {"engine": "whisper"}})
    assert r.status_code == 200
    assert app.state.test_engine.switched == ["whisper"]
    g = client.get("/api/settings").json()
    assert g["asr"]["engine"] == "whisper"


def test_asr_status_and_unload(client):
    r = client.get("/api/asr/status")
    assert r.status_code == 200
    assert r.json()["state"] in ("unloaded", "ready", "loading", "error")
    r2 = client.post("/api/asr/unload")
    assert r2.status_code == 200
    assert r2.json()["state"] == "unloaded"


def test_translate_endpoint(tmp_db, client, monkeypatch):
    from app.services import translate_svc

    async def fake_translate(text, llm_cfg=None, conn=None, client=None):
        return "你好"

    monkeypatch.setattr(translate_svc, "translate", fake_translate)
    r = client.post("/api/translate", json={"text": "hello"})
    assert r.status_code == 200
    assert r.json()["text"] == "你好"


def test_stats(tmp_db, client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["materials"] == 0 and body["attempts"] == 0
