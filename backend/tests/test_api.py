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
        self.calls: list[dict] = []

    def configure(self, **kw):
        pass

    async def create(self, payload, **kw):
        self.payload = payload
        self.calls.append({"payload": payload, **kw})
        return "job-123" if len(self.calls) == 1 else f"job-{len(self.calls)}"

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
    """Import = pure transcription (design §5.2): the endpoint takes no
    mode/blank_count anymore. Extras an old client still sends are
    ignored (Form fields nobody declares are dropped), and the payload
    handed to the job manager carries no generation knobs."""
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
    assert "mode" not in payload
    assert "blank_count" not in payload
    j = client.get("/api/jobs/job-123").json()
    assert j["state"] == "done" and j["material_id"] == "m1"


def test_create_material_requires_source(client):
    r = client.post("/api/materials", data={"name": "Empty"})
    assert r.status_code == 400


def test_create_materials_batch(app, client, tmp_path):
    """Batch import is transcription-only too: mode/blank_count/
    generate_sets are gone; old-client extras are simply ignored."""
    r = client.post(
        "/api/materials/batch",
        data={"name": "Batch A", "mode": "llm", "blank_count": "8",
              "generate_sets": "true"},
        files=[
            ("audios", ("one.mp3", b"one-bytes", "audio/mpeg")),
            ("audios", ("two.m4a", b"two-bytes", "audio/mp4")),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Batch A"
    assert [j["file_name"] for j in body["jobs"]] == ["one.mp3", "two.m4a"]
    assert [j["name"] for j in body["jobs"]] == ["one", "two"]
    assert len(app.state.test_jobs.calls) == 2

    first = app.state.test_jobs.calls[0]
    assert first["batch_id"] == body["batch_id"]
    assert first["position"] == 0
    assert first["payload"]["source_type"] == "upload"
    assert "mode" not in first["payload"]
    assert "blank_count" not in first["payload"]
    assert "generate" not in first["payload"]
    assert Path(first["payload"]["audio_path"]).read_bytes() == b"one-bytes"

    batch = app.state.conn.execute(
        "SELECT * FROM batches WHERE id=?", (body["batch_id"],)
    ).fetchone()
    assert batch["name"] == "Batch A" and batch["total"] == 2


def test_create_materials_batch_validation(client):
    r = client.post("/api/materials/batch", data={"name": "Empty"})
    assert r.status_code == 400

    bad_ext = client.post(
        "/api/materials/batch",
        files=[("audios", ("notes.txt", b"x", "text/plain"))],
    )
    assert bad_ext.status_code == 400
    assert "不支持" in bad_ext.json()["detail"]


def test_batch_status_and_list(tmp_db, client):
    from app.services.jobs import _uid, _now

    now = _now()
    tmp_db.execute(
        "INSERT INTO batches(id,name,total,created_at,updated_at)"
        " VALUES('b1','Batch',3,?,?)",
        (now, now),
    )
    rows = [("done", 100.0, "m1"), ("error", 30.0, None),
            ("transcribing", 30.0, None)]
    for i, (state, pct, mid) in enumerate(rows):
        tmp_db.execute(
            "INSERT INTO jobs(id,state,message,percent,material_id,batch_id,"
            "file_name,position,created_at,updated_at)"
            " VALUES(?,?,?,?,?,'b1',?,?,?,?)",
            (_uid(), state, None, pct, mid, f"{i}.mp3", i, now, now),
        )
    r = client.get("/api/batches/b1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["done"] == 1 and body["error"] == 1 and body["running"] == 1
    assert body["percent"] == 76.7
    assert [j["file_name"] for j in body["jobs"]] == ["0.mp3", "1.mp3", "2.mp3"]

    listed = client.get("/api/batches")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == "b1" and items[0]["running"] == 1

    assert client.get("/api/batches/nope").status_code == 404


def test_materials_list_with_paper_counts(tmp_db, client):
    """The redesign list columns (§六 LibraryView row): papers_count /
    attempts_count / last_practice computed from the paper tables; the
    sets-world columns (sets_count/best_score) are gone."""
    mid = _seed_material(tmp_db)
    from app.services.jobs import _uid, _now

    def _craft_paper():
        paper = {
            "material_id": mid,
            "total_items": 1,
            "warnings": [],
            "groups": [{"type": "completion", "title": "T", "instruction": "",
                        "options": [], "partial": False, "visual": None,
                        "items": [{"number": 1, "type": "completion",
                                   "answer": "castle", "alternatives": []}]}],
        }
        pid = _uid()
        tmp_db.execute(
            "INSERT INTO papers(id,material_id,spec_json,paper_json,created_at)"
            " VALUES(?,?,?,?,?)",
            (pid, mid, json.dumps({"blocks": []}), json.dumps(paper), _now()))
        return pid

    _craft_paper()
    _craft_paper()
    for created in ("2026-10-20T09:00:00+00:00", "2026-10-21T10:00:00+00:00"):
        with tmp_db:
            tmp_db.execute(
                "INSERT INTO paper_attempts(id,paper_id,material_id,created_at)"
                " VALUES(?,?,?,?)", (_uid(), _craft_paper(), mid, created))

    r = client.get("/api/materials")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    row = items[0]
    assert row["id"] == mid
    assert row["papers_count"] == 4
    assert row["attempts_count"] == 2
    assert row["last_practice"] == "2026-10-21T10:00:00+00:00"
    # the score-era columns are gone for good
    assert "sets_count" not in row
    assert "best_score" not in row

    # a material with no papers has zeros / null, never None counts
    other = _seed_material(tmp_db, name="Empty")
    empty = [m for m in client.get("/api/materials").json() if m["id"] == other][0]
    assert empty["papers_count"] == 0
    assert empty["attempts_count"] == 0
    assert empty["last_practice"] is None


def test_material_detail(tmp_db, client):
    mid = _seed_material(tmp_db)
    r = client.get(f"/api/materials/{mid}")
    assert r.status_code == 200
    body = r.json()
    assert body["words"][0]["w"] == "The"
    assert body["sentences"][0] == [0, 6]
    # the sets world is gone from the detail payload; papers have their
    # own listing endpoint (GET /api/materials/{id}/papers)
    assert "sets" not in body
    r404 = client.get("/api/materials/nope")
    assert r404.status_code == 404


def test_material_translations_endpoint(tmp_db, client):
    """GET /materials/{id}/translations (design §7.3): one entry per
    transcript sentence, dst None where the snapshot has no row (missing
    translation never blocks the listen view); 404 for unknown ids."""
    mid = _seed_material(tmp_db)
    for idx, dst in ((0, "小城堡矗立在河附近。"), (2, "一个安静的村庄坐落在湖边。")):
        tmp_db.execute(
            "INSERT INTO material_translations(material_id,sentence_index,"
            "src,dst,created_at) VALUES(?,?,?,?,?)",
            (mid, idx, "stale-src", dst, "2026-10-22T00:00:00"),
        )
    tmp_db.commit()

    r = client.get(f"/api/materials/{mid}/translations")
    assert r.status_code == 200
    body = r.json()
    assert body["material_id"] == mid
    assert [s["index"] for s in body["sentences"]] == [0, 1, 2]
    # src always derives from the current words via the single
    # authoritative §7.1 function, never from the stale stored copy
    assert body["sentences"][0]["src"] == (
        "The little castle stands near the river"
    )
    assert body["sentences"][0]["dst"] == "小城堡矗立在河附近。"
    assert body["sentences"][1]["dst"] is None
    assert body["sentences"][2]["dst"] == "一个安静的村庄坐落在湖边。"

    assert client.get("/api/materials/nope/translations").status_code == 404


def test_material_translations_empty_without_snapshot(tmp_db, client):
    """A material whose pipeline run had no LLM key: the endpoint answers
    200 with dst None everywhere (the page is never blocked)."""
    mid = _seed_material(tmp_db)
    r = client.get(f"/api/materials/{mid}/translations")
    assert r.status_code == 200
    assert r.json()["sentences"] == [
        {"index": 0, "src": "The little castle stands near the river",
         "dst": None},
        {"index": 1, "src": "The tall tower rises above the trees",
         "dst": None},
        {"index": 2, "src": "A quiet village sits beside the lake",
         "dst": None},
    ]


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


def test_put_transcript_realigns_and_stales_papers(tmp_db, client):
    """Transcript edit keeps its §6.1 realign path; the sets-era
    stale_sets response field is gone (papers going stale is covered in
    test_papers_api.py)."""
    mid = _seed_material(tmp_db)
    r = client.put(f"/api/materials/{mid}/transcript",
                   json={"transcript": "The little castle stands near the river."})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript_source"] == "aligned"
    assert "stale_sets" not in body
    # words re-anchored to official text
    assert body["words"][2]["w"] == "castle"


def test_put_transcript_deletes_material_translations(tmp_db, client):
    """转写编辑即作废旧译文 (design §7.2): realignment changes the
    sentence ranges, so the material_translations snapshot dies at the
    same trigger point that stales papers."""
    from app.services.jobs import _now

    mid = _seed_material(tmp_db)
    now = _now()
    tmp_db.executemany(
        "INSERT INTO material_translations(material_id,sentence_index,"
        "src,dst,created_at) VALUES(?,?,?,?,?)",
        [
            (mid, 0, "The little castle stands near the river",
             "小城堡矗立在河边", now),
            (mid, 1, "The tall tower rises above the trees",
             "高塔耸立在树梢之上", now),
        ],
    )
    r = client.put(
        f"/api/materials/{mid}/transcript",
        json={"transcript": "The little castle stands near the river."},
    )
    assert r.status_code == 200
    left = tmp_db.execute(
        "SELECT COUNT(*) c FROM material_translations WHERE material_id=?",
        (mid,),
    ).fetchone()["c"]
    assert left == 0


def test_put_transcript_regenerates_translations(tmp_db, client, monkeypatch):
    """Fix: the deleted snapshot rows must be regenerable. With an LLM
    key configured, the §7.2 translating stage re-runs inline after the
    transcript update commits, so bilingual listening works immediately
    after an edit instead of showing placeholders forever."""
    from app import db
    from app.services import translate_svc

    db.set_setting(tmp_db, "llm", {"provider": "zhipu", "api_key": "test"})

    async def fake_batch(conn, cfg, sentences, **kw):
        return {i: f"译{i}" for i, _ in sentences}

    monkeypatch.setattr(translate_svc, "translate_llm_batch", fake_batch)

    mid = _seed_material(tmp_db)
    r = client.put(
        f"/api/materials/{mid}/transcript",
        json={"transcript": "The little castle stands near the river."},
    )
    assert r.status_code == 200
    rows = tmp_db.execute(
        "SELECT sentence_index,dst FROM material_translations"
        " WHERE material_id=? ORDER BY sentence_index",
        (mid,),
    ).fetchall()
    assert [(r["sentence_index"], r["dst"]) for r in rows] == [(0, "译0")]
    # The intensive-listening snapshot serves the fresh dst immediately.
    snap = client.get(f"/api/materials/{mid}/translations").json()
    assert snap["sentences"][0]["dst"] == "译0"


def test_put_transcript_without_key_skips_regen_silently(tmp_db, client, monkeypatch):
    """No key configured: the PUT still succeeds, no row is written and
    no translation channel is ever called (skip, never an error)."""
    from app.services import translate_svc

    async def bomb(*a, **k):
        raise AssertionError("no translation call is allowed without a key")

    monkeypatch.setattr(translate_svc, "translate_llm_batch", bomb)
    monkeypatch.setattr(translate_svc, "translate", bomb)

    mid = _seed_material(tmp_db)
    r = client.put(
        f"/api/materials/{mid}/transcript",
        json={"transcript": "The little castle stands near the river."},
    )
    assert r.status_code == 200
    assert r.json()["transcript_source"] in ("aligned", "manual")
    assert tmp_db.execute(
        "SELECT COUNT(*) c FROM material_translations WHERE material_id=?",
        (mid,),
    ).fetchone()["c"] == 0


def test_put_transcript_survives_translation_failure(tmp_db, client, monkeypatch):
    """A translation failure must never fail the transcript PUT: the
    inline regen is non-fatal (log/ignore)."""
    from app import db
    from app.services import translate_svc

    db.set_setting(tmp_db, "llm", {"provider": "zhipu", "api_key": "test"})

    async def bomb(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(translate_svc, "translate_llm_batch", bomb)
    monkeypatch.setattr(translate_svc, "translate", bomb)

    mid = _seed_material(tmp_db)
    r = client.put(
        f"/api/materials/{mid}/transcript",
        json={"transcript": "The little castle stands near the river."},
    )
    assert r.status_code == 200
    assert r.json()["words"]  # the realignment result is intact


def test_delete_material_removes_row_and_audio(tmp_db, client, tmp_path):
    audio = tmp_path / "del.mp3"
    audio.write_bytes(b"XYZ")
    mid = _seed_material(tmp_db, audio=str(audio))
    r = client.delete(f"/api/materials/{mid}")
    assert r.status_code == 200
    assert client.get(f"/api/materials/{mid}").status_code == 404
    assert not audio.exists()  # audio file removed


def test_cloze_routes_are_gone(tmp_db, client):
    """The whole sets/attempts/dictation surface is deleted (design
    §5.2): unknown paths must 404 -- paper attempts (in
    routers/papers.py) are the only practice path now."""
    mid = _seed_material(tmp_db)
    assert client.post(
        f"/api/materials/{mid}/sets", json={"mode": "nouns"}
    ).status_code == 404
    assert client.get("/api/sets/x").status_code == 404
    assert client.delete("/api/sets/x").status_code == 404
    assert client.post(
        "/api/sets/x/attempts", json={"answers": []}
    ).status_code == 404
    # dictation mode died with PracticeView's world (design §5.1)
    assert client.post(
        f"/api/materials/{mid}/attempts",
        json={"mode": "dictation", "items": []},
    ).status_code == 404
    assert client.get(f"/api/materials/{mid}/attempts").status_code == 404


def _craft_stored_paper(conn, mid, items):
    """Insert a papers row whose items carry evidence timestamps; returns
    its id (the wrong-words book reads t_start from paper_json, §5.2)."""
    from app.services.jobs import _uid, _now

    paper = {
        "material_id": mid,
        "total_items": len(items),
        "warnings": [],
        "groups": [{
            "type": "completion", "title": "Crafted", "instruction": "",
            "options": [], "partial": False, "visual": None, "items": items,
        }],
    }
    paper_id = _uid()
    with conn:
        conn.execute(
            "INSERT INTO papers(id,material_id,spec_json,paper_json,created_at)"
            " VALUES(?,?,?,?,?)",
            (paper_id, mid, json.dumps({"blocks": []}),
             json.dumps(paper), _now()))
    return paper_id


def test_wrong_words_aggregation(tmp_db, client):
    """The redesigned wrong-words book (§5.2): paper_attempt_items JOIN
    the stored paper JSON -- aggregated by answer text, and the replay
    jump uses the evidence t_start of the most recent wrong attempt."""
    mid = _seed_material(tmp_db)
    paper_id = _craft_stored_paper(tmp_db, mid, [
        {"number": 1, "type": "completion", "answer": "castle",
         "alternatives": [],
         "evidence": [{"i0": 2, "i1": 2, "quote": "castle",
                       "t_start": 2.0, "t_end": 2.5}]},
        {"number": 2, "type": "completion", "answer": "river",
         "alternatives": [],
         "evidence": [{"i0": 6, "i1": 6, "quote": "river",
                       "t_start": 6.0, "t_end": 6.4}]},
    ])

    def _submit(answers):
        res = client.post(f"/api/papers/{paper_id}/attempts",
                          json={"answers": answers})
        assert res.status_code == 200, res.text

    _submit({"1": "xxx", "2": "river"})   # castle wrong
    _submit({"1": "xxx", "2": "river"})   # castle wrong again
    _submit({"1": "castle", "2": "yyy"})  # river wrong once, latest

    r = client.get("/api/review/wrong-words")
    assert r.status_code == 200
    items = r.json()
    by_word = {x["word"]: x for x in items}
    assert by_word["castle"]["times_wrong"] == 2
    assert by_word["river"]["times_wrong"] == 1
    # every row carries the paper coordinates for the replay jump
    assert by_word["castle"]["paper_id"] == paper_id
    assert by_word["castle"]["material_id"] == mid
    assert by_word["castle"]["item_number"] == 1
    assert by_word["castle"]["t_start"] == 2.0
    assert by_word["river"]["t_start"] == 6.0
    # last_at tracks the most recent wrong attempt
    assert by_word["castle"]["last_at"]
    # ranked by frequency first
    assert items[0]["word"] == "castle"


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


def test_settings_test_llm_uses_form_overrides(client, monkeypatch):
    """Typing a key and testing must work before the form is saved."""
    from app.services import llm as llm_mod

    captured = {}

    async def fake_test(cfg):
        captured.update(cfg)
        return True, "连接正常"

    monkeypatch.setattr(llm_mod, "test_connection", fake_test)
    r = client.post("/api/settings/test-llm", json={
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "sk-typed-not-saved",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "连接正常"}
    assert captured["api_key"] == "sk-typed-not-saved"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["model"] == "deepseek-chat"


def test_settings_test_llm_blank_key_falls_back_to_stored(client, monkeypatch):
    from app.services import llm as llm_mod

    client.put("/api/settings", json={"llm": {
        "provider": "custom", "base_url": "https://x.example/v1",
        "model": "my-model", "api_key": "sk-stored"}})
    captured = {}

    async def fake_test(cfg):
        captured.update(cfg)
        return True, "ok"

    monkeypatch.setattr(llm_mod, "test_connection", fake_test)
    r = client.post("/api/settings/test-llm", json={
        "base_url": "https://y.example/v1", "api_key": ""})
    assert r.json()["ok"] is True
    assert captured["api_key"] == "sk-stored"
    assert captured["base_url"] == "https://y.example/v1"


def test_settings_test_llm_without_any_key(client, monkeypatch):
    from app.config import Settings
    from app.routers import settings as settings_router

    monkeypatch.setattr(settings_router, "load_settings", lambda: Settings())
    r = client.post("/api/settings/test-llm", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "API key" in body["message"]


def test_settings_put_rejects_removed_whisper_engine(app, client):
    """"whisper" no longer exists: the old localized 400 still fires."""
    r = client.put("/api/settings", json={"asr": {"engine": "whisper"}})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "whisper" in detail
    # Nothing was persisted or switched.
    assert app.state.test_engine.switched == []


def test_settings_put_rejects_platform_unavailable_engine(app, client, monkeypatch):
    from app.services import engines as engines_mod

    monkeypatch.setattr(
        engines_mod,
        "available_engines",
        lambda *a, **k: (engines_mod.FALLBACK_ENGINE,),
    )
    derived = engines_mod.local_engine()
    r = client.put("/api/settings", json={"asr": {"engine": "parakeet"}})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "parakeet" in detail and engines_mod.FALLBACK_ENGINE in detail
    # Nothing was persisted or switched.
    assert app.state.test_engine.switched == []
    assert client.get("/api/settings").json()["asr"]["engine"] == derived


def test_settings_put_engine_validated_but_never_stored(app, client, tmp_db):
    """An available engine passes validation but is never persisted or
    switched: the engine is always derived from the platform."""
    from app import db as db_mod
    from app.services import engines as engines_mod

    r = client.put("/api/settings", json={
        "asr": {"engine": engines_mod.FALLBACK_ENGINE, "idle_unload_min": 7},
    })
    assert r.status_code == 200
    stored = db_mod.get_setting(tmp_db, "asr")
    assert stored == {"idle_unload_min": 7}
    assert app.state.test_engine.switched == []
    asr = client.get("/api/settings").json()["asr"]
    assert asr["engine"] == engines_mod.local_engine()
    assert asr["idle_unload_min"] == 7


def test_settings_asr_payload_shape(client):
    from app.services import engines as engines_mod

    asr = client.get("/api/settings").json()["asr"]
    assert asr == {
        "mode": "local",
        "engine": engines_mod.local_engine(),
        "idle_unload_min": 10,
        "cloud_base_url": "https://api.groq.com/openai/v1",
        "cloud_model": "whisper-large-v3-turbo",
        "has_cloud_key": False,
        "cloud_key_masked": None,
    }


def test_settings_legacy_asr_row_ignores_unknown_subkeys(app, client, tmp_db):
    """A DB row from the three-engine era must not crash or leak through."""
    from app import db as db_mod
    from app.services import engines as engines_mod

    db_mod.set_setting(
        tmp_db, "asr",
        {"engine": "whisper", "whisper_model": "x", "parakeet_model": "y",
         "idle_unload_min": 3},
    )
    asr = client.get("/api/settings").json()["asr"]
    assert asr == {
        "mode": "local",
        "engine": engines_mod.local_engine(),
        "idle_unload_min": 3,
        "cloud_base_url": "https://api.groq.com/openai/v1",
        "cloud_model": "whisper-large-v3-turbo",
        "has_cloud_key": False,
        "cloud_key_masked": None,
    }


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
    """Redesigned /api/stats (design §5.2): by-type accuracy rows over
    paper_attempt_items -- an empty list until a paper is answered."""
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json() == []
