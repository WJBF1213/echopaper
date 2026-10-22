"""Question-set API: create (llm/nouns/manual), fetch, delete (spec §8)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from app import i18n

from app import db
from app.schemas import SetCreateIn
from app.services import question_gen
from app.services.jobs import manual_blanks, persist_set
from app.services.manual_parse import ManualAnchorError, ManualError, parse_manual
from app.routers.settings import effective_settings, llm_cfg_or_none

router = APIRouter()


def _material_words(conn, material_id: str):
    row = conn.execute(
        "SELECT * FROM materials WHERE id=?", (material_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.material_not_found"))
    return row, json.loads(row["words_json"] or "[]"), json.loads(
        row["sentences_json"] or "[]"
    )


@router.post("/materials/{material_id}/sets")
async def create_set(material_id: str, body: SetCreateIn, request: Request):
    conn = request.app.state.conn
    row, words, sents = _material_words(conn, material_id)
    if not words:
        raise HTTPException(status_code=400, detail=i18n.t("common.material_no_words"))

    if body.mode == "manual":
        text = body.transcript_override or row["transcript"]
        try:
            clean, items = parse_manual(text)
            blanks = manual_blanks(items, words)
        except (ManualError, ManualAnchorError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    elif body.mode in ("llm", "nouns"):
        cfg = None
        if body.mode == "llm":
            settings = effective_settings(conn)
            cfg = llm_cfg_or_none(settings)
        try:
            generated = await question_gen.generate_set(
                words, sents, max(1, body.blank_count), cfg
            )
        except question_gen.QuestionGenError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        blanks = generated.blanks
    else:
        raise HTTPException(status_code=400, detail=i18n.t("common.unknown_mode", mode=body.mode))

    set_id = persist_set(conn, material_id, body.mode, blanks)
    return {"set_id": set_id}


@router.get("/sets/{set_id}")
def get_set(set_id: str, request: Request):
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT * FROM question_sets WHERE id=?", (set_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.set_not_found"))
    blanks = conn.execute(
        "SELECT * FROM blanks WHERE set_id=? ORDER BY position", (set_id,)
    ).fetchall()
    return {
        "id": row["id"],
        "material_id": row["material_id"],
        "mode": row["mode"],
        "blank_count": row["blank_count"],
        "stale": row["stale"],
        "created_at": row["created_at"],
        "blanks": [
            {
                "id": b["id"],
                "position": b["position"],
                "answer": b["answer"],
                "alternatives": json.loads(b["alternatives_json"] or "[]"),
                "word_start": b["word_start"],
                "word_end": b["word_end"],
                "t_start": b["t_start"],
                "t_end": b["t_end"],
                "type": b["type"],
                "word_limit": b["word_limit"],
            }
            for b in blanks
        ],
    }


@router.delete("/sets/{set_id}")
def delete_set(set_id: str, request: Request):
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT id FROM question_sets WHERE id=?", (set_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.set_not_found"))
    with db._write_lock:
        with conn:
            conn.execute("DELETE FROM question_sets WHERE id=?", (set_id,))
    return {"ok": True}
