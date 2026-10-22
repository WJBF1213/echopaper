"""Papers CRUD + answering API (redesign §5.2, Tasks 14-15).

``GET /api/materials/{id}/papers`` lists one summary row per stored
paper (newest first): the question-type composition of the paper that
actually generated (skipped blocks never appear), its item count, the
stale flag and the creation time. ``GET /api/papers/{id}`` returns the
stored spec + full paper JSON; ``DELETE /api/papers/{id}`` removes the
paper (attempts cascade, design §5.1).

Task 15 adds the answering loop (服务端判分, §5.2):
``POST /api/papers/{id}/attempts`` grades server-side via
``app.services.exam_grade`` and persists ``paper_attempts`` +
``paper_attempt_items``; ``GET /api/papers/{id}/attempts`` lists the
paper's attempts newest first; ``GET /api/attempts/{attemptId}`` returns
one attempt's per-item detail; ``GET /api/papers/{id}/stats`` gives the
per-item accuracy the review page is built on (every item of the paper
appears -- zero-attempt items with attempts=0/correct=0). The by-type
cross-paper ``GET /api/stats`` lives in ``routers/stats.py``.

A stale paper (transcript was edited after generation) stays fetchable
and answerable -- the flag is a hint, never a lock (§5.2).
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response

from app import db, i18n
from app.schemas import PaperAttemptIn
from app.services.exam_grade import grade_paper
from app.services.jobs import _now, _uid

router = APIRouter()


def _get_paper(conn: sqlite3.Connection, paper_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, material_id, spec_json, paper_json, generation_json,"
        " stale, created_at FROM papers WHERE id=?",
        (paper_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=i18n.t("common.paper_not_found")
        )
    return row


def _paper_summary(row: sqlite3.Row) -> dict:
    """One list row: the paper's type:count composition (§5.2).

    The composition reflects the generated paper, not the request --
    refused blocks are absent and a shortfall block shows its produced
    count. Same-type groups fold into one entry in group order.
    """
    paper = json.loads(row["paper_json"])
    blocks: list[dict] = []
    by_type: dict[str, dict] = {}
    for group in paper.get("groups") or []:
        entry = by_type.get(group.get("type"))
        if entry is None:
            entry = {"type": group.get("type"), "count": 0}
            by_type[group.get("type")] = entry
            blocks.append(entry)
        entry["count"] += len(group.get("items") or [])
    return {
        "id": row["id"],
        "blocks": blocks,
        "item_count": paper.get("total_items")
        or sum(b["count"] for b in blocks),
        "stale": bool(row["stale"]),
        "created_at": row["created_at"],
    }


@router.get("/materials/{material_id}/papers")
def list_papers(material_id: str, request: Request):
    """The material's papers, newest first."""
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT id FROM materials WHERE id=?", (material_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=i18n.t("common.material_not_found")
        )
    rows = conn.execute(
        "SELECT id, material_id, spec_json, paper_json, stale, created_at"
        " FROM papers WHERE material_id=? ORDER BY created_at DESC, rowid DESC",
        (material_id,),
    ).fetchall()
    return [_paper_summary(r) for r in rows]


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, request: Request):
    """The stored spec and full paper JSON (scene included), plus the
    parsed ``generation`` usage ledger so the client can show what this
    paper's generation cost (calls + tokens, §8 accounting)."""
    row = _get_paper(request.app.state.conn, paper_id)
    return {
        "id": row["id"],
        "material_id": row["material_id"],
        "spec": json.loads(row["spec_json"]),
        "paper": json.loads(row["paper_json"]),
        "generation": json.loads(row["generation_json"] or "null") or [],
        "stale": bool(row["stale"]),
        "created_at": row["created_at"],
    }


@router.delete("/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: str, request: Request):
    """Remove the paper; paper_attempts/items cascade (design §5.1)."""
    conn = request.app.state.conn
    _get_paper(conn, paper_id)
    with db._write_lock:
        with conn:
            conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
    return Response(status_code=204)


# --------------------------------------------- answering (design §5.2, T15)


def _int_keys(answers: dict[str, str]) -> dict[int, str]:
    """JSON object keys are strings; item numbers are ints. Keys that are
    not an item number (non-numeric, or matching no item) are ignored --
    a deliberate choice: the caller's stale view of the paper must not
    make the submission fail (matching the old sets-endpoint leniency).
    """
    out: dict[int, str] = {}
    for key, value in answers.items():
        try:
            out[int(key)] = value
        except (TypeError, ValueError):
            continue
    return out


@router.post("/papers/{paper_id}/attempts")
def submit_attempt(paper_id: str, body: PaperAttemptIn, request: Request):
    """Submit answers: grade server-side, persist, return per-item
    results (design §5.2). Unanswered items grade wrong (user_answer
    None); the score itself is NOT persisted -- only per-item flags.
    """
    conn = request.app.state.conn
    row = _get_paper(conn, paper_id)
    items = grade_paper(json.loads(row["paper_json"]), _int_keys(body.answers))
    attempt_id = _uid()
    created_at = _now()
    with db._write_lock:
        with conn:
            conn.execute(
                "INSERT INTO paper_attempts(id,paper_id,material_id,"
                "created_at) VALUES(?,?,?,?)",
                (attempt_id, paper_id, row["material_id"], created_at),
            )
            for item in items:
                conn.execute(
                    "INSERT INTO paper_attempt_items(attempt_id,item_number,"
                    "item_type,user_answer,correct,expected)"
                    " VALUES(?,?,?,?,?,?)",
                    (
                        attempt_id,
                        item["item_number"],
                        item["item_type"],
                        item["user_answer"],
                        1 if item["correct"] else 0,
                        item["expected"],
                    ),
                )
    return {"attempt_id": attempt_id, "created_at": created_at, "items": items}


@router.get("/papers/{paper_id}/attempts")
def list_attempts(paper_id: str, request: Request):
    """The paper's attempts, newest first, with their item counts (the
    per-item detail lives on GET /api/attempts/{attemptId})."""
    conn = request.app.state.conn
    _get_paper(conn, paper_id)
    rows = conn.execute(
        "SELECT a.id, a.created_at, COUNT(i.item_number) AS item_count"
        " FROM paper_attempts a"
        " LEFT JOIN paper_attempt_items i ON i.attempt_id=a.id"
        " WHERE a.paper_id=? GROUP BY a.id"
        " ORDER BY a.created_at DESC, a.rowid DESC",
        (paper_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, request: Request):
    """One attempt's per-item detail, in item order (§5.2 单次作答回顾)."""
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT id, paper_id, material_id, created_at"
        " FROM paper_attempts WHERE id=?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=i18n.t("common.attempt_not_found")
        )
    items = conn.execute(
        "SELECT item_number, item_type, user_answer, correct, expected"
        " FROM paper_attempt_items WHERE attempt_id=? ORDER BY item_number",
        (attempt_id,),
    ).fetchall()
    return {
        "id": row["id"],
        "paper_id": row["paper_id"],
        "material_id": row["material_id"],
        "created_at": row["created_at"],
        "items": [
            {
                "item_number": i["item_number"],
                "item_type": i["item_type"],
                "user_answer": i["user_answer"],
                "correct": bool(i["correct"]),
                "expected": i["expected"],
            }
            for i in items
        ],
    }


@router.get("/papers/{paper_id}/stats")
def paper_stats(paper_id: str, request: Request):
    """Per-item accuracy for one paper -- the review page's main data
    (§5.2). Every item of the paper is listed in paper order; items no
    one has answered yet appear with attempts=0/correct=0.
    """
    conn = request.app.state.conn
    row = _get_paper(conn, paper_id)
    paper = json.loads(row["paper_json"])
    counts = {
        r["item_number"]: (r["attempts"], r["correct"])
        for r in conn.execute(
            "SELECT i.item_number, COUNT(*) AS attempts,"
            " SUM(i.correct) AS correct"
            " FROM paper_attempt_items i"
            " JOIN paper_attempts a ON i.attempt_id=a.id"
            " WHERE a.paper_id=? GROUP BY i.item_number",
            (paper_id,),
        )
    }
    stats = []
    for group in paper.get("groups") or []:
        for item in group.get("items") or []:
            attempts, correct = counts.get(item.get("number"), (0, 0))
            stats.append(
                {
                    "item_number": item.get("number"),
                    "item_type": item.get("type"),
                    "attempts": attempts,
                    "correct": correct,
                }
            )
    return stats
