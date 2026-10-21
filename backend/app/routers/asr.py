"""ASR engine status / manual load / unload (spec §7, §8)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.services.engines import EngineError

router = APIRouter()


@router.get("/asr/status")
def asr_status(request: Request):
    return request.app.state.engine_manager.status()


@router.post("/asr/load")
async def asr_load(request: Request):
    manager = request.app.state.engine_manager
    try:
        await manager.acquire()  # triggers lazy load (first-use download)
        await manager.release()
    except EngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return manager.status()


@router.post("/asr/unload")
async def asr_unload(request: Request):
    result = await request.app.state.engine_manager.unload_now()
    if result.get("busy"):
        raise HTTPException(status_code=409, detail=result.get("detail"))
    return result
