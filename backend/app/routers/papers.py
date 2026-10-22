"""Papers CRUD API (redesign §5.2, Task 14).

``GET /api/materials/{id}/papers`` lists one summary row per stored
paper (newest first): the question-type composition of the paper that
actually generated (skipped blocks never appear), its item count, the
stale flag and the creation time. ``GET /api/papers/{id}`` returns the
stored spec + full paper JSON; ``DELETE /api/papers/{id}`` removes the
paper (attempts cascade, design §5.1).

A stale paper (transcript was edited after generation) stays fetchable
and answerable -- the flag is a hint, never a lock (§5.2).
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response

from app import db, i18n

router = APIRouter()


def _get_paper(conn: sqlite3.Connection, paper_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, material_id, spec_json, paper_json, stale, created_at"
        " FROM papers WHERE id=?",
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
    """The stored spec and full paper JSON (scene included)."""
    row = _get_paper(request.app.state.conn, paper_id)
    return {
        "id": row["id"],
        "material_id": row["material_id"],
        "spec": json.loads(row["spec_json"]),
        "paper": json.loads(row["paper_json"]),
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
