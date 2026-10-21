"""Task B10 tests: material ingestion job pipeline (all engines/LLM/net mocked)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app import db
from app.services import jobs as jobs_mod
from app.services.jobs import JobManager


def _raw_asr_words(words, start=0.0, step=1.0, p=0.95):
    return [
        {"w": w, "s": start + i * step, "e": start + i * step + 0.4, "p": p}
        for i, w in enumerate(words)
    ]


class FakeEngineManager:
    def __init__(self, raw):
        self.raw = raw
        self.acquired = 0
        self.released = 0

    async def acquire(self):
        self.acquired += 1
        raw = self.raw

        def transcribe(path):
            return raw

        return SimpleNamespace(name="fake", transcribe=transcribe)

    async def release(self):
        self.released += 1


def make_jm(tmp_db, raw_words=None, llm_cfg=None):
    raw = raw_words if raw_words is not None else _raw_asr_words(
        ["Hello", "there", "friend", "The", "castle", "stands", "near",
         "the", "river", "today", "again", "friends"]
    )
    engine = FakeEngineManager(raw)
    jm = JobManager(
        conn=tmp_db,
        engine_manager=engine,
        llm_cfg_fn=(lambda: llm_cfg) if llm_cfg is not None else (lambda: None),
        data_dir=None,  # per-test tmp
    )
    return jm, engine


async def _run_to_completion(jm, job_id, timeout=5.0):
    async def wait():
        while True:
            job = jm.get(job_id)
            if job["state"] in ("done", "error"):
                return job
            await asyncio.sleep(0)

    return await asyncio.wait_for(wait(), timeout)


@pytest.mark.asyncio
async def test_job_persisted_and_queryable(tmp_db, tmp_path):
    jm, engine = make_jm(tmp_db)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")
    job_id = await jm.create({
        "name": "Test material",
        "source_type": "upload",
        "audio_path": str(audio),
        "blank_count": 3,
        "mode": "nouns",
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    assert job["material_id"]
    assert engine.acquired == 1 and engine.released == 1
    row = tmp_db.execute(
        "SELECT * FROM materials WHERE id=?", (job["material_id"],)
    ).fetchone()
    assert row is not None
    assert row["source_type"] == "upload"
    assert json.loads(row["words_json"])
    sets = tmp_db.execute(
        "SELECT * FROM question_sets WHERE material_id=?", (job["material_id"],)
    ).fetchall()
    assert len(sets) == 1
    assert sets[0]["mode"] == "nouns"
    blanks = tmp_db.execute(
        "SELECT * FROM blanks WHERE set_id=?", (sets[0]["id"],)
    ).fetchall()
    assert 1 <= len(blanks) <= 3


@pytest.mark.asyncio
async def test_upload_with_transcript_aligns(tmp_db, tmp_path):
    # ASR words deliberately imperfect (missing 'very', misheard 'ther")
    raw = _raw_asr_words(["Hello", "ther", "big", "castle", "stands"])
    jm, _ = make_jm(tmp_db, raw_words=raw)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")
    transcript = "Hello there very big castle stands."
    job_id = await jm.create({
        "name": "Aligned",
        "source_type": "upload",
        "audio_path": str(audio),
        "transcript": transcript,
        "blank_count": 2,
        "mode": "nouns",
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    row = tmp_db.execute(
        "SELECT * FROM materials WHERE id=?", (job["material_id"],)
    ).fetchone()
    assert row["transcript_source"] == "aligned"
    words = json.loads(row["words_json"])
    assert [w["w"] for w in words] == [
        "Hello", "there", "very", "big", "castle", "stands",
    ]
    # official spelling won; ASR timestamps carried
    assert words[1]["w"] == "there"
    assert words[0]["s"] == 0.0


@pytest.mark.asyncio
async def test_align_low_rate_falls_back_to_asr(tmp_db, tmp_path):
    raw = _raw_asr_words(["alpha", "bravo", "castle", "delta", "echo"])
    jm, _ = make_jm(tmp_db, raw_words=raw)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")
    job_id = await jm.create({
        "name": "Mismatch",
        "source_type": "upload",
        "audio_path": str(audio),
        "transcript": "one two three four five six seven",
        "blank_count": 2,
        "mode": "nouns",
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    row = tmp_db.execute(
        "SELECT * FROM materials WHERE id=?", (job["material_id"],)
    ).fetchone()
    assert row["transcript_source"] == "asr"
    words = json.loads(row["words_json"])
    assert [w["w"] for w in words][:2] == ["alpha", "bravo"]
    assert "对齐" in (job["message"] or "")


@pytest.mark.asyncio
async def test_audio_download_failure_job_error(tmp_db, tmp_path):
    jm, _ = make_jm(tmp_db)
    data_dir = tmp_path / "data"
    job_id = await jm.create({
        "name": "Bad URL",
        "source_type": "url",
        "audio_url": "http://127.0.0.1:1/nope.mp3",
        "blank_count": 3,
        "mode": "nouns",
        "data_dir": data_dir,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "error"
    audio_dir = data_dir / "audio"
    leftovers = list(audio_dir.glob("*")) if audio_dir.exists() else []
    assert leftovers == []  # partial download cleaned up
    assert tmp_db.execute("SELECT COUNT(*) c FROM materials").fetchone()["c"] == 0


@pytest.mark.asyncio
async def test_transcript_only_material(tmp_db, tmp_path):
    jm, engine = make_jm(tmp_db)
    job_id = await jm.create({
        "name": "Text only",
        "source_type": "upload",
        "transcript": "The little castle stands near the river. "
                     "The tall tower rises above the trees. "
                     "A quiet village sits beside the lake.",
        "blank_count": 3,
        "mode": "nouns",
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    assert engine.acquired == 0  # no audio -> no ASR
    row = tmp_db.execute(
        "SELECT * FROM materials WHERE id=?", (job["material_id"],)
    ).fetchone()
    assert row["transcript_source"] == "manual"
    assert row["audio_path"] is None
    words = json.loads(row["words_json"])
    assert all(w["s"] == 0.0 for w in words)


@pytest.mark.asyncio
async def test_manual_bracket_mode_ingest(tmp_db, tmp_path):
    jm, _ = make_jm(tmp_db)
    transcript = (
        "The [castle] stands near the river. "
        "A quiet [village] sits beside the lake."
    )
    job_id = await jm.create({
        "name": "Manual",
        "source_type": "upload",
        "transcript": transcript,
        "blank_count": 0,
        "mode": "manual",
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    row = tmp_db.execute(
        "SELECT transcript FROM materials WHERE id=?", (job["material_id"],)
    ).fetchone()
    assert "[" not in row["transcript"] and "]" not in row["transcript"]
    sets = tmp_db.execute(
        "SELECT * FROM question_sets WHERE material_id=?", (job["material_id"],)
    ).fetchall()
    blanks = tmp_db.execute(
        "SELECT * FROM blanks WHERE set_id=?", (sets[0]["id"],)
    ).fetchall()
    assert sorted(b["answer"] for b in blanks) == ["castle", "village"]


@pytest.mark.asyncio
async def test_batch_jobs_transcribe_and_store_each(tmp_db, tmp_path):
    jm, engine = make_jm(tmp_db)
    audio_a = tmp_path / "a.mp3"
    audio_b = tmp_path / "b.mp3"
    audio_a.write_bytes(b"ID3-a")
    audio_b.write_bytes(b"ID3-b")
    now = jobs_mod._now()
    tmp_db.execute(
        "INSERT INTO batches(id,name,total,created_at,updated_at)"
        " VALUES('b1','Batch',2,?,?)",
        (now, now),
    )

    async def enqueue(name, path, position):
        return await jm.create(
            {
                "name": name,
                "source_type": "upload",
                "audio_path": str(path),
                "blank_count": 0,
                "mode": "none",
                "generate": False,
                "data_dir": tmp_path,
            },
            batch_id="b1",
            file_name=f"{name}.mp3",
            position=position,
        )

    j1 = await enqueue("one", audio_a, 0)
    j2 = await enqueue("two", audio_b, 1)
    jobs = await asyncio.gather(
        _run_to_completion(jm, j1), _run_to_completion(jm, j2)
    )

    assert [j["state"] for j in jobs] == ["done", "done"]
    assert len({j["material_id"] for j in jobs}) == 2
    assert engine.acquired == 2 and engine.released == 2
    # transcription-only: no sets were generated
    assert tmp_db.execute(
        "SELECT COUNT(*) c FROM question_sets").fetchone()["c"] == 0
    # both audio files were adopted into data_dir/audio
    assert len(list((tmp_path / "audio").glob("*"))) == 2
    rows = tmp_db.execute(
        "SELECT batch_id,file_name,position FROM jobs ORDER BY position"
    ).fetchall()
    assert [r["batch_id"] for r in rows] == ["b1", "b1"]
    assert [r["file_name"] for r in rows] == ["one.mp3", "two.mp3"]


@pytest.mark.asyncio
async def test_batch_job_failure_does_not_block_siblings(tmp_db, tmp_path):
    jm, _ = make_jm(tmp_db)
    good = tmp_path / "good.mp3"
    good.write_bytes(b"ID3-good")

    j_bad = await jm.create(
        {
            "name": "bad",
            "source_type": "upload",
            "audio_path": str(tmp_path / "missing.mp3"),
            "blank_count": 0,
            "mode": "none",
            "generate": False,
            "data_dir": tmp_path,
        },
        batch_id="b2",
        file_name="missing.mp3",
        position=0,
    )
    j_good = await jm.create(
        {
            "name": "good",
            "source_type": "upload",
            "audio_path": str(good),
            "blank_count": 0,
            "mode": "none",
            "generate": False,
            "data_dir": tmp_path,
        },
        batch_id="b2",
        file_name="good.mp3",
        position=1,
    )
    bad, ok = await asyncio.gather(
        _run_to_completion(jm, j_bad), _run_to_completion(jm, j_good)
    )
    assert bad["state"] == "error"
    assert ok["state"] == "done" and ok["material_id"]
    assert tmp_db.execute(
        "SELECT COUNT(*) c FROM materials").fetchone()["c"] == 1


@pytest.mark.asyncio
async def test_failed_transcription_cleans_adopted_audio(tmp_db, tmp_path):
    class FailingEngine:
        async def acquire(self):
            def transcribe(path):
                raise RuntimeError("asr exploded")

            return SimpleNamespace(name="fake", transcribe=transcribe)

        async def release(self):
            pass

    jm = JobManager(conn=tmp_db, engine_manager=FailingEngine(), data_dir=tmp_path)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")
    job_id = await jm.create({
        "name": "Broken",
        "source_type": "upload",
        "audio_path": str(audio),
        "blank_count": 0,
        "mode": "none",
        "generate": False,
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "error"
    assert list((tmp_path / "audio").glob("*")) == []
    assert tmp_db.execute(
        "SELECT COUNT(*) c FROM materials").fetchone()["c"] == 0


def test_reconcile_interrupted_marks_stale_jobs(tmp_db):
    now = jobs_mod._now()
    tmp_db.executemany(
        "INSERT INTO jobs(id,state,percent,created_at,updated_at)"
        " VALUES(?,?,?,?,?)",
        [("j1", "transcribing", 30.0, now, now),
         ("j2", "done", 100.0, now, now)],
    )
    count = jobs_mod.reconcile_interrupted(tmp_db)
    assert count == 1
    rows = {r["id"]: r for r in tmp_db.execute("SELECT * FROM jobs")}
    assert rows["j1"]["state"] == "error"
    assert "重启" in rows["j1"]["message"]
    assert rows["j2"]["state"] == "done"


@pytest.mark.asyncio
async def test_llm_mode_generates_set(tmp_db, tmp_path, monkeypatch):
    from app.services import question_gen

    jm, _ = make_jm(tmp_db, llm_cfg={"provider": "zhipu", "api_key": "k"})
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")

    async def fake_generate(words_json, sentences, blank_count, llm_cfg=None, **kw):
        from app.services.question_gen import Blank, GeneratedSet

        return GeneratedSet(
            blanks=[Blank(position=1, answer=words_json[2]["w"], word_start=2,
                          word_end=2, t_start=words_json[2]["s"],
                          t_end=words_json[2]["e"], type="noun")],
            source="llm",
        )

    monkeypatch.setattr(question_gen, "generate_set", fake_generate)
    job_id = await jm.create({
        "name": "LLM",
        "source_type": "upload",
        "audio_path": str(audio),
        "blank_count": 1,
        "mode": "llm",
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    sets = tmp_db.execute(
        "SELECT * FROM question_sets WHERE material_id=?", (job["material_id"],)
    ).fetchall()
    assert sets[0]["mode"] == "llm"
    blanks = tmp_db.execute(
        "SELECT * FROM blanks WHERE set_id=?", (sets[0]["id"],)
    ).fetchall()
    assert len(blanks) == 1
