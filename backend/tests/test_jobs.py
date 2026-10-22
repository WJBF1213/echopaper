"""Material ingestion job pipeline tests (redesign §5.3, Task 18).

The pipeline is transcription-only: ``queued -> (downloading) ->
transcribing -> done``. There is no generating stage; the cloze tables
(``question_sets``/``blanks``) no longer exist at all (db.py drops them
at init, Task 19), so pasted ``[[ ]]`` brackets stay literal (manual
parsing is gone) and nothing can ever write set/blank rows. All
engines/LLM/net are mocked.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

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


def make_jm(tmp_db, raw_words=None):
    raw = raw_words if raw_words is not None else _raw_asr_words(
        ["Hello", "there", "friend", "The", "castle", "stands", "near",
         "the", "river", "today", "again", "friends"]
    )
    engine = FakeEngineManager(raw)
    jm = JobManager(
        conn=tmp_db,
        engine_manager=engine,
        data_dir=None,  # per-test tmp
    )
    return jm, engine


async def _run_to_completion(jm, job_id, timeout=5.0, seen=None):
    async def wait():
        while True:
            job = jm.get(job_id)
            if seen is not None:
                seen.append(job["state"])
            if job["state"] in ("done", "error"):
                return job
            await asyncio.sleep(0)

    return await asyncio.wait_for(wait(), timeout)


def _assert_no_sets_written(conn):
    """Import is transcription-only: the cloze tables are dropped at init
    (fresh schema v3, Task 19), so they cannot exist — a fortiori the
    pipeline writes nothing to them."""
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert not ({"question_sets", "blanks"} & tables)


@pytest.mark.asyncio
async def test_job_persisted_and_queryable(tmp_db, tmp_path):
    jm, engine = make_jm(tmp_db)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")
    job_id = await jm.create({
        "name": "Test material",
        "source_type": "upload",
        "audio_path": str(audio),
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
    _assert_no_sets_written(tmp_db)


@pytest.mark.asyncio
async def test_pipeline_states_never_include_generating(tmp_db, tmp_path):
    """The slimmed pipeline (§5.3): queued -> transcribing -> done for an
    upload; the generating stage must not exist at all."""
    jm, _ = make_jm(tmp_db)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3-fake")
    job_id = await jm.create({
        "name": "Stages",
        "source_type": "upload",
        "audio_path": str(audio),
        "data_dir": tmp_path,
    })
    seen: list[str] = []
    job = await _run_to_completion(jm, job_id, seen=seen)
    assert job["state"] == "done"
    assert "transcribing" in seen
    assert "generating" not in seen
    assert seen[-1] == "done"
    _assert_no_sets_written(tmp_db)


@pytest.mark.asyncio
async def test_url_import_passes_downloading_stage(
    tmp_db, tmp_path, monkeypatch
):
    """URL imports add the downloading stage: queued -> downloading ->
    transcribing -> done (the only four states a job can take)."""
    audio = tmp_path / "dl.mp3"
    audio.write_bytes(b"ID3-dl")

    async def fake_save_upload(data_dir, url=None, **kw):
        await asyncio.sleep(0)  # a real download yields; so must the fake
        return audio, 3.0

    monkeypatch.setattr(jobs_mod.audio_mod, "save_upload", fake_save_upload)
    jm, _ = make_jm(tmp_db)
    job_id = await jm.create({
        "name": "From URL",
        "source_type": "url",
        "audio_url": "http://example.com/a.mp3",
        "data_dir": tmp_path,
    })
    seen: list[str] = []
    job = await _run_to_completion(jm, job_id, seen=seen)
    assert job["state"] == "done"
    assert "downloading" in seen
    assert "transcribing" in seen
    assert "generating" not in seen
    assert set(seen) <= {"queued", "downloading", "transcribing", "done"}
    _assert_no_sets_written(tmp_db)


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
async def test_audio_download_failure_job_error(tmp_db, tmp_path, monkeypatch):
    from app.services.audio import AudioError

    async def fake_save_upload(data_dir, url=None, **kw):
        raise AudioError("download boom")

    monkeypatch.setattr(jobs_mod.audio_mod, "save_upload", fake_save_upload)
    jm, _ = make_jm(tmp_db)
    data_dir = tmp_path / "data"
    job_id = await jm.create({
        "name": "Bad URL",
        "source_type": "url",
        "audio_url": "http://127.0.0.1:1/nope.mp3",
        "data_dir": data_dir,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "error"
    assert "boom" in (job["message"] or "")
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
async def test_bracket_markers_not_parsed(tmp_db, tmp_path):
    """Import = pure transcription (design §5.2): pasted ``[[ ]]`` / ``[]``
    markers have no parsing path anymore -- nothing extracts answers from
    them and no set/blank rows appear. Like every other edge punctuation
    (commas, quotes) the bracket characters are normalized away from the
    stored words; their content stays as plain ordinary text."""
    jm, _ = make_jm(tmp_db)
    transcript = (
        "The [[castle]] stands near the river. "
        "A quiet [] sits beside the lake."
    )
    job_id = await jm.create({
        "name": "Marked",
        "source_type": "upload",
        "transcript": transcript,
        "data_dir": tmp_path,
    })
    job = await _run_to_completion(jm, job_id)
    assert job["state"] == "done"
    row = tmp_db.execute(
        "SELECT * FROM materials WHERE id=?", (job["material_id"],)
    ).fetchone()
    assert row["transcript_source"] == "manual"
    words = json.loads(row["words_json"])
    # the bracketed span is ordinary text now -- not an extracted answer
    assert "castle" in [w["w"] for w in words]
    # a punctuation-only token ("[]") normalizes to nothing
    assert "" not in [w["w"] for w in words]
    _assert_no_sets_written(tmp_db)


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
    _assert_no_sets_written(tmp_db)
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
