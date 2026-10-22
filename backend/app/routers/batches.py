"""Batch import status: aggregate progress over a set of material jobs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import i18n

router = APIRouter()

_JOB_COLUMNS = (
    "id,state,message,percent,material_id,file_name,position,"
    "created_at,updated_at"
)


def _counts(jobs: list[dict]) -> dict:
    total = len(jobs)
    done = sum(1 for j in jobs if j["state"] == "done")
    error = sum(1 for j in jobs if j["state"] == "error")
    running = total - done - error
    if total:
        percent = sum(
            100.0 if j["state"] in ("done", "error")
            else float(j["percent"] or 0.0)
            for j in jobs
        ) / total
    else:
        percent = 0.0
    return {
        "total": total,
        "done": done,
        "error": error,
        "running": running,
        "percent": round(percent, 1),
    }


@router.get("/batches")
def list_batches(request: Request):
    rows = request.app.state.conn.execute(
        """
        SELECT b.id, b.name, b.total, b.created_at,
               SUM(CASE WHEN j.state='done' THEN 1 ELSE 0 END) AS done,
               SUM(CASE WHEN j.state='error' THEN 1 ELSE 0 END) AS error,
               SUM(CASE WHEN j.state NOT IN ('done','error')
                        THEN 1 ELSE 0 END) AS running,
               MAX(j.updated_at) AS updated_at,
               AVG(CASE WHEN j.state IN ('done','error') THEN 100.0
                        ELSE COALESCE(j.percent, 0) END) AS percent
        FROM batches b
        LEFT JOIN jobs j ON j.batch_id = b.id
        GROUP BY b.id
        ORDER BY b.created_at DESC
        LIMIT 30
        """
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["done"] = item["done"] or 0
        item["error"] = item["error"] or 0
        item["running"] = item["running"] or 0
        item["percent"] = round(float(item["percent"] or 0.0), 1)
        out.append(item)
    return out


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, request: Request):
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT id,name,total,created_at,updated_at FROM batches WHERE id=?",
        (batch_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.batch_not_found"))
    jobs = [
        {
            "job_id": j["id"],
            "state": j["state"],
            "message": j["message"],
            "percent": j["percent"],
            "material_id": j["material_id"],
            "file_name": j["file_name"],
            "position": j["position"],
            "created_at": j["created_at"],
            "updated_at": j["updated_at"],
        }
        for j in conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE batch_id=?"
            " ORDER BY position, created_at",
            (batch_id,),
        ).fetchall()
    ]
    result = dict(row)
    result.update(_counts(jobs))
    result["jobs"] = jobs
    return result
