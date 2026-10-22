"""Global stats API (redesign §5.2, Task 15).

``GET /api/stats`` aggregates by item type across ALL papers: how many
items of each type were answered anywhere and the correct share. It
replaces the sets-world handler that lived in ``routers/review.py``
(avg score over the legacy ``attempts`` table): the redesign drops the
score concept entirely (design §5.1 成绩不重要 -- per-item correctness
only), so the old handler was removed from review.py and this is the
single implementation on the same path. review.py now serves only the
paper-based wrong-words book (Task 17).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/stats")
def stats(request: Request):
    """By-type accuracy over every persisted paper attempt item
    (``[{item_type, attempts, correct, accuracy}]``, type order).
    Types nobody has answered yet simply do not appear."""
    conn = request.app.state.conn
    rows = conn.execute(
        "SELECT item_type, COUNT(*) AS attempts, SUM(correct) AS correct"
        " FROM paper_attempt_items GROUP BY item_type ORDER BY item_type"
    ).fetchall()
    return [
        {
            "item_type": r["item_type"],
            "attempts": r["attempts"],
            "correct": r["correct"],
            "accuracy": round(r["correct"] / r["attempts"], 4),
        }
        for r in rows
    ]
