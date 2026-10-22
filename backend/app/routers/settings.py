"""Settings API: read (masked) / partial update (write-only key) /
test-llm probe. Effective settings = config defaults (.env/env) merged
with the DB settings table (spec §8)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import db
from app.config import load_settings
from app.schemas import LlmTestIn, SettingsIn
from app.services import llm as llm_mod

router = APIRouter()


def effective_settings(conn) -> dict:
    """config(.env/env) defaults overlaid by stored DB settings."""
    s = load_settings()
    out = {
        "llm": {
            "provider": s.llm.provider,
            "base_url": s.llm.base_url,
            "model": s.llm.model,
            "api_key": s.llm.api_key,
            "max_context_tokens": s.llm.max_context_tokens,
        },
        "asr": {
            "engine": s.asr.engine,
            "parakeet_model": s.asr.parakeet_model,
            "whisper_model": s.asr.whisper_model,
            "idle_unload_min": s.asr.idle_unload_min,
        },
        "gen": {"blank_count": s.gen.blank_count},
    }
    for key in ("llm", "asr", "gen"):
        stored = db.get_setting(conn, key)
        if isinstance(stored, dict):
            out[key].update(stored)
    out["llm"]["max_context_tokens"] = llm_mod.clamp_max_context(
        out["llm"].get("max_context_tokens")
    )
    return out


def mask_key(key: str) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _public(settings: dict) -> dict:
    llm = dict(settings["llm"])
    key = llm.pop("api_key", "") or ""
    llm["has_key"] = bool(key)
    llm["key_masked"] = mask_key(key)
    return {"llm": llm, "asr": settings["asr"], "gen": settings["gen"]}


def llm_cfg_or_none(settings: dict) -> dict | None:
    """LLM config for services; None when no key (programmatic fallback)."""
    llm = settings["llm"]
    if not (llm.get("api_key") or "").strip():
        return None
    return llm


@router.get("/settings")
def get_settings(request: Request):
    conn = request.app.state.conn
    return _public(effective_settings(conn))


@router.put("/settings")
async def put_settings(body: SettingsIn, request: Request):
    conn = request.app.state.conn
    current = effective_settings(conn)

    if body.llm is not None:
        patch = body.llm.model_dump(exclude_none=True)
        if "max_context_tokens" in patch:
            patch["max_context_tokens"] = llm_mod.clamp_max_context(
                patch["max_context_tokens"]
            )
        if "api_key" in patch and not (patch["api_key"] or "").strip():
            patch.pop("api_key")  # empty key keeps the stored one
        current["llm"].update(patch)
        db.set_setting(conn, "llm", current["llm"])
    if body.asr is not None:
        patch = body.asr.model_dump(exclude_none=True)
        old_engine = current["asr"].get("engine")
        current["asr"].update(patch)
        db.set_setting(conn, "asr", current["asr"])
        new_engine = current["asr"].get("engine")
        if patch.get("engine") and new_engine != old_engine:
            result = await request.app.state.engine_manager.switch(new_engine)
            if result.get("busy"):
                raise HTTPException(status_code=409, detail=result.get("detail"))
    if body.gen is not None:
        patch = body.gen.model_dump(exclude_none=True)
        current["gen"].update(patch)
        db.set_setting(conn, "gen", current["gen"])

    return _public(effective_settings(conn))


@router.post("/settings/test-llm")
async def test_llm(request: Request, body: LlmTestIn | None = None):
    """Probe the LLM with the form's current values.

    The settings form can be tested before it is saved, so the request body
    may override any LLM field. A blank ``api_key`` means "keep using the
    stored key" rather than "there is no key".
    """
    settings = effective_settings(request.app.state.conn)
    cfg = dict(settings["llm"])
    if body is not None:
        patch = body.model_dump(exclude_none=True)
        key = (patch.get("api_key") or "").strip()
        if key:
            patch["api_key"] = key
        else:
            patch.pop("api_key", None)
        cfg.update(patch)
    if not (cfg.get("api_key") or "").strip():
        return {
            "ok": False,
            "message": "未配置 LLM API key：请填写密钥后点击「保存并测试」",
        }
    ok, message = await llm_mod.test_connection(cfg)
    return {"ok": ok, "message": message}
