"""Materials API: list/create/detail/transcript-edit/delete/audio (spec §8)."""
from __future__ import annotations

import json
import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path

from app import i18n
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app import db
from app.schemas import TranscriptIn
from app.services import align as align_mod
from app.services import audio as audio_mod
from app.services import normalize

router = APIRouter()

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
MAX_BATCH_FILES = 50


def _get_material(conn, material_id: str):
    row = conn.execute(
        "SELECT * FROM materials WHERE id=?", (material_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.material_not_found"))
    return row


@router.get("/materials")
def list_materials(request: Request, q: str = ""):
    """The library list (design §六 LibraryView row): paper-based counts.
    The sets-era columns (sets_count/best_score) died with the score
    concept -- counts now come from papers/paper_attempts."""
    conn = request.app.state.conn
    like = f"%{q}%"
    rows = conn.execute(
        """
        SELECT m.id, m.name, m.duration_s, m.created_at, m.transcript_source,
               (SELECT COUNT(*) FROM papers p
                 WHERE p.material_id = m.id) AS papers_count,
               (SELECT COUNT(*) FROM paper_attempts a
                 WHERE a.material_id = m.id) AS attempts_count,
               (SELECT MAX(a.created_at) FROM paper_attempts a
                 WHERE a.material_id = m.id) AS last_practice,
               (m.audio_path IS NOT NULL) AS has_audio
        FROM materials m
        WHERE m.name LIKE ?
        ORDER BY m.created_at DESC
        """,
        (like,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/materials")
async def create_material(
    request: Request,
    name: str = Form(""),
    audio: UploadFile | None = File(None),
    audio_url: str | None = Form(None),
    transcript: str | None = Form(None),
):
    """Import = pure transcription (design §5.2): no mode/blank_count
    parameters anymore; extra form fields an old client still sends are
    ignored by FastAPI."""
    if audio is None and not audio_url and not transcript:
        raise HTTPException(
            status_code=400, detail=i18n.t("common.need_input")
        )
    payload: dict = {
        "name": name,
        "source_type": "url" if (audio is None and audio_url) else "upload",
        "transcript": transcript or None,
        "data_dir": str(request.app.state.data_dir),
    }
    if audio is not None:
        payload["audio_bytes"] = await audio.read()
        payload["audio_filename"] = audio.filename
    elif audio_url:
        payload["audio_url"] = audio_url
    job_id = await request.app.state.jobs_manager.create(payload)
    return {"job_id": job_id}


@router.post("/materials/batch")
async def create_materials_batch(
    request: Request,
    audios: list[UploadFile] | None = File(None),
    name: str = Form(""),
):
    """Batch import: one material per audio, transcribed and stored.

    Audio is streamed to ``data_dir/incoming`` before enqueueing, so the
    request never buffers the whole batch in memory. Transcription and
    storage only -- papers are generated later from the material page
    (design §5.3: batch never auto-generates).
    """
    files = [f for f in (audios or []) if f and f.filename]
    if not files:
        raise HTTPException(status_code=400, detail=i18n.t("common.need_one_audio"))
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=i18n.t("common.too_many_files", limit=MAX_BATCH_FILES),
        )
    for upload in files:
        if not audio_mod.has_supported_ext(upload.filename):
            raise HTTPException(
                status_code=400,
                detail=i18n.t("common.unsupported_audio", name=upload.filename),
            )

    data_dir = Path(request.app.state.data_dir)
    batch_id = uuid.uuid4().hex[:12]
    created = _now()
    batch_name = name.strip() or (
        i18n.t("common.batch_default_name", time=datetime.now().strftime("%m-%d %H:%M"))
    )

    staged: list[Path] = []
    try:
        for upload in files:
            staged.append(await audio_mod.stage_upload(data_dir, upload))
        with db._write_lock:
            with request.app.state.conn:
                request.app.state.conn.execute(
                    "INSERT INTO batches(id,name,total,created_at,updated_at)"
                    " VALUES(?,?,?,?,?)",
                    (batch_id, batch_name, len(files), created, created),
                )
        jobs: list[dict] = []
        for position, (upload, path) in enumerate(zip(files, staged)):
            filename = upload.filename or path.name
            material_name = Path(filename).stem.strip() or i18n.t("common.untitled_material")
            job_id = await request.app.state.jobs_manager.create(
                {
                    "name": material_name,
                    "source_type": "upload",
                    "audio_path": str(path),
                    "data_dir": str(data_dir),
                },
                batch_id=batch_id,
                file_name=filename,
                position=position,
            )
            jobs.append({
                "job_id": job_id,
                "file_name": filename,
                "name": material_name,
                "position": position,
            })
    except HTTPException:
        raise
    except Exception as exc:
        for path in staged:
            try:
                path.unlink()
            except OSError:
                pass
        with db._write_lock:
            with request.app.state.conn:
                request.app.state.conn.execute(
                    "DELETE FROM jobs WHERE batch_id=?", (batch_id,)
                )
                request.app.state.conn.execute(
                    "DELETE FROM batches WHERE id=?", (batch_id,)
                )
        raise HTTPException(
            status_code=400, detail=i18n.t("common.batch_failed", error=exc)
        ) from exc

    return {"batch_id": batch_id, "name": batch_name, "jobs": jobs}


@router.get("/materials/{material_id}")
def material_detail(material_id: str, request: Request):
    conn = request.app.state.conn
    row = _get_material(conn, material_id)
    return {
        "id": row["id"],
        "name": row["name"],
        "source_type": row["source_type"],
        "audio_url": row["audio_url"],
        "duration_s": row["duration_s"],
        "has_audio": bool(row["audio_path"]),
        "transcript": row["transcript"],
        "transcript_source": row["transcript_source"],
        "asr_model": row["asr_model"],
        "words": json.loads(row["words_json"] or "[]"),
        "sentences": json.loads(row["sentences_json"] or "[]"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.put("/materials/{material_id}/transcript")
def put_transcript(material_id: str, body: TranscriptIn, request: Request):
    """Post-edit / paste official transcript: re-align + re-anchor (§6.1).

    Every stored paper of the material goes stale (design §5.2 -- stale
    papers stay fetchable/answerable, the flag is only a hint)."""
    conn = request.app.state.conn
    row = _get_material(conn, material_id)
    words = json.loads(row["words_json"] or "[]")
    sents = json.loads(row["sentences_json"] or "[]")
    has_timestamps = bool(words) and any(
        w.get("s") != w.get("e") for w in words
    )

    message = None
    if has_timestamps and words:
        off_words, off_sents = _pseudo(body.transcript)
        aligned, rate = align_mod.align_transcript(
            [w["w"] for w in off_words], words
        )
        if align_mod.should_use_aligned(rate):
            words, sents = aligned, off_sents
            source = "aligned"
        else:
            source = row["transcript_source"]
            message = i18n.t("common.align_failed_keep", rate=rate)
    else:
        words, sents = _pseudo(body.transcript)
        source = "manual"

    with db._write_lock:
        with conn:
            conn.execute(
                "UPDATE materials SET transcript=?, transcript_source=?,"
                "words_json=?, sentences_json=?, updated_at=? WHERE id=?",
                (
                    normalize.words_to_text(words, sents),
                    source,
                    json.dumps(words, ensure_ascii=False),
                    json.dumps(sents),
                    _now(),
                    material_id,
                ),
            )
            # Papers are self-contained (answers/evidence embedded) so a
            # stale paper stays answerable -- only flag the drift (§5.2).
            conn.execute(
                "UPDATE papers SET stale=1 WHERE material_id=?",
                (material_id,),
            )
    return {
        "id": material_id,
        "transcript_source": source,
        "message": message,
        "words": words,
        "sentences": sents,
    }


@router.delete("/materials/{material_id}")
def delete_material(material_id: str, request: Request):
    conn = request.app.state.conn
    row = _get_material(conn, material_id)
    if row["audio_path"]:
        audio = Path(row["audio_path"])
        if audio.is_file():
            try:
                audio.unlink()
            except OSError:
                pass
    with db._write_lock:
        with conn:
            conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
    return {"ok": True}


@router.get("/materials/{material_id}/audio")
def material_audio(material_id: str, request: Request):
    conn = request.app.state.conn
    row = _get_material(conn, material_id)
    if not row["audio_path"]:
        raise HTTPException(status_code=404, detail=i18n.t("common.audio_missing"))
    path = Path(row["audio_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail=i18n.t("common.audio_file_missing"))
    media_type = mimetypes.guess_type(str(path))[0] or "audio/mpeg"
    size = path.stat().st_size
    range_header = request.headers.get("range")

    match = _RANGE_RE.fullmatch(range_header.strip()) if range_header else None
    if match:
        a, b = match.group(1), match.group(2)
        if not a and not b:
            start, end = 0, size - 1
        elif not a:  # bytes=-N -> last N bytes
            n = int(b)
            start, end = max(0, size - n), size - 1
        else:
            start = int(a)
            end = int(b) if b else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
            )
        data = path.read_bytes()[start : end + 1]
        return Response(
            content=data,
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
            },
        )
    return FileResponse(
        path, media_type=media_type, headers={"Accept-Ranges": "bytes"}
    )


def _pseudo(text: str):
    raw = [{"w": tok, "s": 0.0, "e": 0.0} for tok in text.split()]
    return normalize.build_words_segments(raw)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = request.app.state.jobs_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.job_not_found"))
    return job


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
