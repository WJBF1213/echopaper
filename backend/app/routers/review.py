"""Review API: cross-material wrong-word book (spec §8).

The old ``GET /api/stats`` handler (avg score over the legacy attempts
table) moved out in Task 15: the redesign drops scores (design §5.1)
and the by-type accuracy implementation now lives in
``routers/stats.py``. The wrong-words book below still reads the legacy
tables until the review endpoints are rebuilt on paper_attempt_items
(design §5.2, P19).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/review/wrong-words")
def wrong_words(request: Request):
    conn = request.app.state.conn
    items: dict[tuple[str, str], dict] = {}

    # blank-based wrongs
    rows = conn.execute(
        """
        SELECT b.answer AS word, COUNT(*) AS times_wrong,
               MAX(a.finished_at) AS last_at, a.material_id AS material_id,
               MAX(b.t_start) AS t_start
        FROM attempt_items ai
        JOIN attempts a ON ai.attempt_id = a.id
        JOIN blanks b ON ai.blank_id = b.id
        WHERE ai.correct = 0
        GROUP BY b.answer, a.material_id
        """
    ).fetchall()
    for r in rows:
        items[(r["word"], r["material_id"])] = dict(r)

    # dictation wrongs (word_index based; resolve timestamps per material)
    d_rows = conn.execute(
        """
        SELECT ai.expected AS word, a.material_id AS material_id,
               ai.word_index AS word_index, a.finished_at AS last_at
        FROM attempt_items ai
        JOIN attempts a ON ai.attempt_id = a.id
        WHERE ai.correct = 0 AND ai.blank_id IS NULL AND ai.expected != ''
        """
    ).fetchall()
    if d_rows:
        words_cache: dict[str, list] = {}
        for r in d_rows:
            mid = r["material_id"]
            if mid not in words_cache:
                mrow = conn.execute(
                    "SELECT words_json FROM materials WHERE id=?", (mid,)
                ).fetchone()
                words_cache[mid] = json.loads(mrow["words_json"]) if mrow else []
            words = words_cache[mid]
            t_start = None
            idx = r["word_index"]
            if idx is not None and 0 <= idx < len(words):
                t_start = words[idx].get("s")
            key = (r["word"], mid)
            entry = items.get(key)
            if entry is None:
                entry = {
                    "word": r["word"],
                    "times_wrong": 0,
                    "last_at": r["last_at"],
                    "material_id": mid,
                    "t_start": t_start,
                }
                items[key] = entry
            entry["times_wrong"] += 1
            if r["last_at"] and (not entry["last_at"] or r["last_at"] > entry["last_at"]):
                entry["last_at"] = r["last_at"]

    out = sorted(
        items.values(), key=lambda x: (-x["times_wrong"], x["word"])
    )
    return out
