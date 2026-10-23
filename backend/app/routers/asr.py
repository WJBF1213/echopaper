"""ASR engine status / manual load / unload (spec §7, §8); cloud probe
(POST /api/asr/test-cloud, Task 3)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import i18n
from app.schemas import CloudAsrTestIn
from app.services import cloud_engine as cloud_engine_mod
from app.services.engines import EngineError
from app.routers.settings import effective_settings

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


@router.post("/asr/test-cloud")
async def test_cloud_asr(request: Request, body: CloudAsrTestIn | None = None):
    """Probe the cloud transcription endpoint with the form's values.

    The settings form can be tested before it is saved, so the request
    body may override any cloud field. A blank ``cloud_api_key`` means
    "keep using the stored key" rather than "there is no key" — the
    same convention as POST /api/settings/test-llm.
    """
    settings = effective_settings(request.app.state.conn)
    cfg = dict(settings["asr"])
    if body is not None:
        patch = body.model_dump(exclude_none=True)
        key = (patch.get("cloud_api_key") or "").strip()
        if key:
            patch["cloud_api_key"] = key
        else:
            patch.pop("cloud_api_key", None)
        cfg.update(patch)
    if not (cfg.get("cloud_api_key") or "").strip():
        return {
            "ok": False,
            "message": i18n.t("asr.no_key"),
        }
    ok, message = await cloud_engine_mod.test_cloud_connection(cfg)
    return {"ok": ok, "message": message}
