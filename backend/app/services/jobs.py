"""Material ingestion job orchestration.

State machine per job: queued -> (downloading, URL imports only) ->
transcribing -> done | error, every transition persisted to the jobs
table. Import is pure transcription (redesign §5.3): audio + pasted
transcript -> alignment (§6.1, low rate falls back to ASR words with a
notice); transcript-only -> manual source (no timestamps, ``[[ ]]``
markers stay literal). Transcription runs in a thread via the engine
manager's acquire/release (one at a time). Papers are generated later
on demand from the material page -- never during import.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import db, i18n
from app.services import align as align_mod
from app.services import audio as audio_mod
from app.services import normalize


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _pseudo_words(text: str) -> tuple[list[dict], list[list[int]]]:
    """Normalize a plain text into words_json-like structures (no audio)."""
    raw = [{"w": tok, "s": 0.0, "e": 0.0} for tok in text.split()]
    return normalize.build_words_segments(raw)


class JobManager:
    def __init__(
        self,
        conn=None,
        engine_manager=None,
        data_dir: Path | None = None,
    ):
        self.conn = conn
        self.engine = engine_manager
        self.data_dir = data_dir
        self._tasks: dict[str, asyncio.Task] = {}

    def configure(
        self,
        conn=None,
        engine_manager=None,
        data_dir=None,
    ) -> None:
        if conn is not None:
            self.conn = conn
        if engine_manager is not None:
            self.engine = engine_manager
        if data_dir is not None:
            self.data_dir = data_dir

    # ------------------------------------------------------------- job rows
    def _update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [_now(), job_id]
        with db._write_lock:
            with self.conn:
                self.conn.execute(
                    f"UPDATE jobs SET {sets}, updated_at=? WHERE id=?", values
                )

    def get(self, job_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------- creation
    async def create(
        self,
        payload: dict,
        *,
        batch_id: str | None = None,
        file_name: str | None = None,
        position: int | None = None,
    ) -> str:
        if self.conn is None:
            raise RuntimeError("JobManager 未绑定数据库连接")
        job_id = _uid()
        created = _now()
        with db._write_lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO jobs(id,state,message,percent,material_id,"
                    "batch_id,file_name,position,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id, "queued", None, 0.0, None,
                        batch_id, file_name, position, created, created,
                    ),
                )
                if batch_id is not None:
                    self.conn.execute(
                        "UPDATE batches SET updated_at=? WHERE id=?",
                        (created, batch_id),
                    )
        task = asyncio.create_task(self._run(job_id, dict(payload)))
        self._tasks[job_id] = task
        return job_id

    # ------------------------------------------------------------- pipeline
    async def _run(self, job_id: str, p: dict) -> None:
        try:
            await self._pipeline(job_id, p)
        except Exception as exc:  # noqa: BLE001 - job must never crash app
            # Clean up first so observers of state=error see the final disk state.
            await self._cleanup_orphan_audio(job_id, p)
            self._update(job_id, state="error", message=f"{type(exc).__name__}: {exc}")

    async def _cleanup_orphan_audio(self, job_id: str, p: dict) -> None:
        """Remove staged/adopted audio when the material was never stored."""
        job = self.get(job_id)
        if job and job.get("material_id"):
            return
        for key in ("audio_path", "staged_path"):
            value = p.get(key)
            if not value:
                continue
            path = Path(value)
            # A material row always owns its audio, even if the job row
            # has not been updated yet.
            owned = self.conn.execute(
                "SELECT 1 FROM materials WHERE audio_path=? LIMIT 1",
                (str(path),),
            ).fetchone()
            if owned or not path.is_file():
                continue
            try:
                await asyncio.to_thread(path.unlink)
            except OSError:
                pass

    async def _pipeline(self, job_id: str, p: dict) -> None:
        data_dir = Path(p.get("data_dir") or self.data_dir or "data")
        transcript: str | None = p.get("transcript") or None
        note: str | None = None

        # -- stage 1: obtain audio (downloading applies to URL only) --------
        audio_path: Path | None = None
        duration: float | None = None
        # The staged path is replaced once the file is adopted into data/audio;
        # keep it so an early failure can still clean up the upload.
        p.setdefault("staged_path", p.get("audio_path"))
        if p.get("audio_url") and not p.get("audio_path"):
            self._update(job_id, state="downloading", percent=5,
                         message=i18n.t("job.downloading"))
            audio_path, duration = await audio_mod.save_upload(
                data_dir, url=p["audio_url"]
            )
        elif p.get("audio_path"):
            src = Path(p["audio_path"])
            if not src.is_file():
                raise FileNotFoundError(i18n.t("job.audio_not_found", path=src))
            audio_path, duration = await self._adopt_audio(data_dir, src)
        elif p.get("audio_bytes") is not None:
            audio_path, duration = await audio_mod.save_upload(
                data_dir, filename=p.get("audio_filename"),
                data=p["audio_bytes"],
            )
        # Point cleanup at wherever the audio actually lives now.
        p["audio_path"] = str(audio_path) if audio_path else None

        # -- stage 2: words (ASR / align / manual) ---------------------------
        engine_obj = None
        if audio_path is not None:
            self._update(job_id, state="transcribing", percent=30,
                         message=i18n.t("job.transcribing"))
            engine_obj = await self._acquire_engine()
            try:
                raw_words = await asyncio.to_thread(
                    engine_obj.transcribe, str(audio_path)
                )
            finally:
                await self._release_engine()
            asr_words, asr_sents = normalize.build_words_segments(raw_words)
            if transcript:
                off_words, off_sents = _pseudo_words(transcript)
                aligned, rate = align_mod.align_transcript(
                    [w["w"] for w in off_words], asr_words
                )
                if align_mod.should_use_aligned(rate):
                    words, sents, source = aligned, off_sents, "aligned"
                else:
                    words, sents, source = asr_words, asr_sents, "asr"
                    note = i18n.t("common.align_failed", rate=rate)
            else:
                words, sents, source = asr_words, asr_sents, "asr"
        elif transcript:
            words, sents = _pseudo_words(transcript)
            source = "manual"
        else:
            raise ValueError(i18n.t("job.no_input"))

        # -- stage 3: persist material -> done --------------------------------
        material_id = _uid()
        created = _now()
        audio_rel = str(audio_path) if audio_path else None
        with db._write_lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO materials(id,name,source_type,audio_path,"
                    "audio_url,duration_s,transcript,transcript_source,"
                    "words_json,sentences_json,asr_model,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        material_id,
                        p.get("name") or i18n.t("common.untitled_material"),
                        p.get("source_type") or ("url" if p.get("audio_url") else "upload"),
                        audio_rel,
                        p.get("audio_url"),
                        duration,
                        normalize.words_to_text(words, sents),
                        source,
                        json.dumps(words, ensure_ascii=False),
                        json.dumps(sents),
                        getattr(engine_obj, "name", None) if audio_path else None,
                        created, created,
                    ),
                )
        self._update(job_id, state="done", percent=100.0,
                     message=note, material_id=material_id)

    # ------------------------------------------------------------- helpers
    async def _adopt_audio(self, data_dir: Path, src: Path) -> tuple[Path, float | None]:
        """Move an uploaded temp file into data_dir/audio for safekeeping."""
        audio_dir = Path(data_dir) / "audio"
        await asyncio.to_thread(audio_dir.mkdir, parents=True, exist_ok=True)
        dst = audio_dir / f"{_uid()}{src.suffix.lower() or '.mp3'}"
        await asyncio.to_thread(shutil.move, str(src), str(dst))
        duration = await asyncio.to_thread(audio_mod.probe_duration, dst)
        return dst, duration

    async def _acquire_engine(self):
        if self.engine is None:
            from app.services.engines import manager

            return await manager.acquire()
        return await self.engine.acquire()

    async def _release_engine(self) -> None:
        if self.engine is None:
            from app.services.engines import manager

            await manager.release()
        else:
            await self.engine.release()


def reconcile_interrupted(conn) -> int:
    """Mark jobs left mid-flight by a previous process as failed.

    Tasks live only in memory: after a restart their rows would otherwise
    stay "transcribing" forever and a batch would look permanently active.
    """
    with db._write_lock:
        with conn:
            cur = conn.execute(
                "UPDATE jobs SET state='error',"
                " message=COALESCE(message, ?),"
                " updated_at=? WHERE state NOT IN ('done','error')",
                (i18n.t("common.restart_interrupted"), _now()),
            )
    return cur.rowcount


#: process-wide singleton; app startup wires conn/engine/llm (B12)
jobs = JobManager()
