"""Material ingestion job orchestration (Task B10).

State machine per job: queued -> (downloading) -> transcribing ->
generating -> done | error, every transition persisted to the jobs
table. Audio + pasted transcript -> alignment (§6.1, low rate falls
back to ASR words with a notice); transcript-only -> manual source
(no timestamps). Transcription runs in a thread via the engine
manager's acquire/release (one at a time).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app import db
from app.services import align as align_mod
from app.services import audio as audio_mod
from app.services import normalize
from app.services import question_gen
from app.services.manual_parse import anchor_manual, parse_manual


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
        llm_cfg_fn: Callable[[], Any] | None = None,
        data_dir: Path | None = None,
    ):
        self.conn = conn
        self.engine = engine_manager
        self.llm_cfg_fn = llm_cfg_fn or (lambda: None)
        self.data_dir = data_dir
        self._tasks: dict[str, asyncio.Task] = {}

    def configure(
        self,
        conn=None,
        engine_manager=None,
        llm_cfg_fn=None,
        data_dir=None,
    ) -> None:
        if conn is not None:
            self.conn = conn
        if engine_manager is not None:
            self.engine = engine_manager
        if llm_cfg_fn is not None:
            self.llm_cfg_fn = llm_cfg_fn
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
    async def create(self, payload: dict) -> str:
        if self.conn is None:
            raise RuntimeError("JobManager 未绑定数据库连接")
        job_id = _uid()
        with db._write_lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO jobs(id,state,message,percent,material_id,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (job_id, "queued", None, 0.0, None, _now(), _now()),
                )
        task = asyncio.create_task(self._run(job_id, dict(payload)))
        self._tasks[job_id] = task
        return job_id

    # ------------------------------------------------------------- pipeline
    async def _run(self, job_id: str, p: dict) -> None:
        try:
            await self._pipeline(job_id, p)
        except Exception as exc:  # noqa: BLE001 - job must never crash app
            self._update(job_id, state="error", message=f"{type(exc).__name__}: {exc}")

    async def _pipeline(self, job_id: str, p: dict) -> None:
        data_dir = Path(p.get("data_dir") or self.data_dir or "data")
        mode = p.get("mode") or "llm"
        blank_count = int(p.get("blank_count") or 10)
        transcript: str | None = p.get("transcript") or None
        note: str | None = None

        # -- manual mode: strip brackets first, clean text is authoritative
        manual_items: list[dict] = []
        if transcript and mode == "manual":
            transcript, manual_items = parse_manual(transcript)

        # -- stage 1: obtain audio ------------------------------------------------
        audio_path: Path | None = None
        duration: float | None = None
        if p.get("audio_url") and not p.get("audio_path"):
            self._update(job_id, state="downloading", percent=5,
                         message="下载音频")
            audio_path, duration = await audio_mod.save_upload(
                data_dir, url=p["audio_url"]
            )
        elif p.get("audio_path"):
            src = Path(p["audio_path"])
            if not src.is_file():
                raise FileNotFoundError(f"音频文件不存在：{src}")
            audio_path, duration = await self._adopt_audio(data_dir, src)
        elif p.get("audio_bytes") is not None:
            audio_path, duration = await audio_mod.save_upload(
                data_dir, filename=p.get("audio_filename"),
                data=p["audio_bytes"],
            )

        # -- stage 2: words (ASR / align / manual) ---------------------------------
        if audio_path is not None:
            self._update(job_id, state="transcribing", percent=30,
                         message="本地识别中")
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
                    note = (f"原文对齐失败（匹配率 {rate:.0%}），"
                            "已改用识别文本")
            else:
                words, sents, source = asr_words, asr_sents, "asr"
        elif transcript:
            words, sents = _pseudo_words(transcript)
            source = "manual"
        else:
            raise ValueError("缺少音频或转写文本，无法创建材料")

        # -- stage 3: persist material ---------------------------------------------
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
                        p.get("name") or "未命名材料",
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
        self._update(job_id, state="generating", percent=75,
                     message="生成题目", material_id=material_id)

        # -- stage 4: question set --------------------------------------------------
        if mode == "manual":
            blanks = self._manual_blanks(manual_items, words)
            set_mode = "manual"
        else:
            cfg = self.llm_cfg_fn() if mode == "llm" else None
            generated = await question_gen.generate_set(
                words, sents, blank_count, cfg
            )
            blanks = generated.blanks
            set_mode = mode
        self._persist_set(material_id, set_mode, blanks)

        self._update(job_id, state="done", percent=100.0,
                     message=note, material_id=material_id)

    # ------------------------------------------------------------- helpers
    async def _adopt_audio(self, data_dir: Path, src: Path) -> tuple[Path, float | None]:
        """Move an uploaded temp file into data_dir/audio for safekeeping."""
        audio_dir = Path(data_dir) / "audio"
        await asyncio.to_thread(audio_dir.mkdir, True, True)
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

    def _manual_blanks(self, manual_items: list[dict], words: list[dict]) -> list:
        from app.services.question_gen import Blank, derive_word_limit

        anchored = anchor_manual(manual_items, words)
        blanks = []
        for position, a in enumerate(anchored, start=1):
            i0, i1 = a["i0"], a["i1"]
            blanks.append(
                Blank(
                    position=position,
                    answer=a["answer"],
                    word_start=i0,
                    word_end=i1,
                    t_start=float(words[i0].get("s", 0.0)),
                    t_end=float(words[i1].get("e", 0.0)),
                    type="noun",
                    word_limit=derive_word_limit(i1 - i0 + 1),
                )
            )
        return blanks

    def _persist_set(self, material_id: str, mode: str, blanks: list) -> str:
        set_id = _uid()
        with db._write_lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO question_sets(id,material_id,mode,blank_count,"
                    "params_json,stale,created_at) VALUES(?,?,?,?,?,?,?)",
                    (set_id, material_id, mode, len(blanks), "{}", 0, _now()),
                )
                for b in blanks:
                    self.conn.execute(
                        "INSERT INTO blanks(id,set_id,position,answer,"
                        "alternatives_json,word_start,word_end,t_start,t_end,"
                        "type,word_limit) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            _uid(), set_id, b.position, b.answer,
                            json.dumps(getattr(b, "alternatives", []) or []),
                            b.word_start, b.word_end, b.t_start, b.t_end,
                            b.type, b.word_limit,
                        ),
                    )
        return set_id


#: process-wide singleton; app startup wires conn/engine/llm (B12)
jobs = JobManager()
