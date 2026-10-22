"""Attempts API: server-side grading + history (spec §8)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app import i18n

from app import db
from app.schemas import AttemptIn, DictationIn
from app.services.grading import grade
from app.services.jobs import _uid

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/sets/{set_id}/attempts")
def submit_attempt(set_id: str, body: AttemptIn, request: Request):
    conn = request.app.state.conn
    set_row = conn.execute(
        "SELECT * FROM question_sets WHERE id=?", (set_id,)
    ).fetchone()
    if set_row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.set_not_found"))
    blanks = {
        b["id"]: b
        for b in conn.execute(
            "SELECT * FROM blanks WHERE set_id=? ORDER BY position", (set_id,)
        ).fetchall()
    }
    results = []
    ok_count = 0
    seen = set()
    for ans in body.answers:
        blank = blanks.get(ans.blank_id)
        if blank is None or ans.blank_id in seen:
            continue
        seen.add(ans.blank_id)
        alts = json.loads(blank["alternatives_json"] or "[]")
        correct = grade(ans.text, blank["answer"], alts)
        ok_count += 1 if correct else 0
        results.append(
            {
                "blank_id": ans.blank_id,
                "correct": correct,
                "expected": blank["answer"],
                "user_text": ans.text,
            }
        )
    attempt_id = _uid()
    with db._write_lock:
        with conn:
            conn.execute(
                "INSERT INTO attempts(id,set_id,material_id,mode,started_at,"
                "finished_at,ok,total,duration_s) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    set_id,
                    set_row["material_id"],
                    set_row["mode"],
                    _now(),
                    _now(),
                    ok_count,
                    len(results),
                    body.duration_s,
                ),
            )
            for r in results:
                conn.execute(
                    "INSERT INTO attempt_items(attempt_id,blank_id,word_index,"
                    "user_text,correct,expected) VALUES(?,?,?,?,?,?)",
                    (
                        attempt_id,
                        r["blank_id"],
                        None,
                        r["user_text"],
                        1 if r["correct"] else 0,
                        r["expected"],
                    ),
                )
    return {
        "attempt_id": attempt_id,
        "ok": ok_count,
        "total": len(results),
        "results": results,
    }


@router.post("/materials/{material_id}/attempts")
def submit_dictation(material_id: str, body: DictationIn, request: Request):
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT * FROM materials WHERE id=?", (material_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.material_not_found"))
    words = json.loads(row["words_json"] or "[]")
    results = []
    ok_count = 0
    for item in body.items:
        if 0 <= item.word_index < len(words):
            expected = words[item.word_index]["w"]
            t_start = words[item.word_index].get("s")
        else:
            expected, t_start = "", None
        correct = bool(expected) and grade(item.text, expected, [])
        ok_count += 1 if correct else 0
        results.append(
            {
                "word_index": item.word_index,
                "correct": correct,
                "expected": expected,
                "t_start": t_start,
                "user_text": item.text,
            }
        )
    attempt_id = _uid()
    with db._write_lock:
        with conn:
            conn.execute(
                "INSERT INTO attempts(id,set_id,material_id,mode,started_at,"
                "finished_at,ok,total,duration_s) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    None,
                    material_id,
                    "dictation",
                    _now(),
                    _now(),
                    ok_count,
                    len(results),
                    body.duration_s,
                ),
            )
            for r in results:
                conn.execute(
                    "INSERT INTO attempt_items(attempt_id,blank_id,word_index,"
                    "user_text,correct,expected) VALUES(?,?,?,?,?,?)",
                    (
                        attempt_id,
                        None,
                        r["word_index"],
                        r["user_text"],
                        1 if r["correct"] else 0,
                        r["expected"],
                    ),
                )
    return {
        "attempt_id": attempt_id,
        "ok": ok_count,
        "total": len(results),
        "results": results,
    }


@router.get("/materials/{material_id}/attempts")
def attempt_history(material_id: str, request: Request):
    conn = request.app.state.conn
    rows = conn.execute(
        "SELECT id, set_id, mode, started_at, finished_at, ok, total,"
        " duration_s FROM attempts WHERE material_id=?"
        " ORDER BY finished_at DESC",
        (material_id,),
    ).fetchall()
    return [dict(r) for r in rows]
