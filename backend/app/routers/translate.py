"""Translate API: sentence EN->ZH with cache + fallbacks (spec §8)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import TranslateIn
from app.services import translate_svc
from app.services.translate_svc import TranslateError
from app.routers.settings import effective_settings, llm_cfg_or_none

router = APIRouter()


@router.post("/translate")
async def translate(body: TranslateIn, request: Request):
    settings = effective_settings(request.app.state.conn)
    cfg = llm_cfg_or_none(settings)
    try:
        result = await translate_svc.translate(body.text, cfg)
    except TranslateError as exc:
        return {"text": "", "error": str(exc)}
    return {"text": result}
