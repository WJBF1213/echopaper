"""Review API: cross-material wrong-word book (spec §8, redesign §5.2).

Rewritten in Task 17 on the paper data model: the book aggregates
``paper_attempt_items`` where ``correct = 0`` by answer text, and every
row carries the paper coordinates (paper/material/item number) plus the
``t_start`` of the item's evidence read from the stored ``paper_json``
-- the "点击重听" jump navigates to that paper (design §5.2). The old
sets/dictation-table implementation died with those tables' data; the
legacy stats handler moved to ``routers/stats.py`` in Task 15.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request

router = APIRouter()


def _evidence_start(paper_cache: dict[str, dict], conn, paper_id: str,
                    item_number: int) -> float | None:
    """t_start of the item's first evidence span, from the stored paper
    JSON (answers/evidence are embedded in the paper, §5.1). Cached per
    paper; unknown numbers (paper edited?) simply yield None."""
    paper = paper_cache.get(paper_id)
    if paper is None:
        row = conn.execute(
            "SELECT paper_json FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
        paper = json.loads(row["paper_json"]) if row else {}
        paper_cache[paper_id] = paper
    for group in paper.get("groups") or []:
        for item in group.get("items") or []:
            if item.get("number") == item_number:
                evidence = item.get("evidence") or []
                if evidence:
                    return evidence[0].get("t_start")
                return None
    return None


@router.get("/review/wrong-words")
def wrong_words(request: Request):
    """Wrong items aggregated by answer text (design §六 ReviewView row).
    Each row keeps the MOST RECENT wrong occurrence's coordinates so the
    replay button jumps to a paper that still contains the item."""
    conn = request.app.state.conn
    rows = conn.execute(
        """
        SELECT i.expected, i.item_number, a.paper_id, a.material_id,
               a.created_at
        FROM paper_attempt_items i
        JOIN paper_attempts a ON i.attempt_id = a.id
        WHERE i.correct = 0 AND i.expected IS NOT NULL AND i.expected != ''
        ORDER BY a.created_at
        """
    ).fetchall()

    paper_cache: dict[str, dict] = {}
    items: dict[str, dict] = {}
    for r in rows:
        word = r["expected"]
        entry = items.get(word)
        if entry is None:
            entry = {
                "word": word,
                "times_wrong": 0,
                "last_at": r["created_at"],
                "material_id": r["material_id"],
                "paper_id": r["paper_id"],
                "item_number": r["item_number"],
                "t_start": _evidence_start(
                    paper_cache, conn, r["paper_id"], r["item_number"]
                ),
            }
            items[word] = entry
        entry["times_wrong"] += 1
        # rows arrive in created_at order, so the last one seen is the
        # most recent: refresh the jump coordinates as we go.
        entry["last_at"] = r["created_at"]
        entry["material_id"] = r["material_id"]
        entry["paper_id"] = r["paper_id"]
        entry["item_number"] = r["item_number"]
        entry["t_start"] = _evidence_start(
            paper_cache, conn, r["paper_id"], r["item_number"]
        )

    return sorted(
        items.values(), key=lambda x: (-x["times_wrong"], x["word"])
    )
