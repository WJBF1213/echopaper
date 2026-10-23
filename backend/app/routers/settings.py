"""Settings API: read (masked) / partial update (write-only key) /
test-llm probe. Effective settings = config defaults (.env/env) merged
with the DB settings table (spec §8)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import db, i18n
from app.config import load_settings
from app.schemas import LlmTestIn, SettingsIn
from app.services import engines as engines_mod
from app.services import llm as llm_mod
from app.services.engines import EngineError

router = APIRouter()

#: stored ``asr`` subkeys the readers honor. Legacy rows from the
#: three-engine era may still carry ``engine`` / ``*_model`` subkeys;
#: they are ignored, and a fresh PUT rewrites the row without them.
_ASR_STORED_KEYS = (
    "mode",
    "idle_unload_min",
    "cloud_base_url",
    "cloud_model",
    "cloud_api_key",
)
ASR_MODES = ("local", "cloud")


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
            "mode": s.asr.mode,
            "engine": engines_mod.local_engine(),
            "idle_unload_min": s.asr.idle_unload_min,
            "cloud_base_url": s.asr.cloud_base_url,
            "cloud_model": s.asr.cloud_model,
            "cloud_api_key": s.asr.cloud_api_key,
        },
    }
    stored = db.get_setting(conn, "llm")
    if isinstance(stored, dict):
        out["llm"].update(stored)
    stored = db.get_setting(conn, "asr")
    if isinstance(stored, dict):
        for key in _ASR_STORED_KEYS:
            if key in stored:
                out["asr"][key] = stored[key]
    # engine is derived, never stored: cloud when the mode says so,
    # else the platform's one local engine
    mode = out["asr"].get("mode") or "local"
    out["asr"]["engine"] = "cloud" if mode == "cloud" else engines_mod.local_engine()
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
    asr = dict(settings["asr"])
    cloud_key = asr.pop("cloud_api_key", "") or ""
    asr["has_cloud_key"] = bool(cloud_key)
    asr["cloud_key_masked"] = mask_key(cloud_key)
    return {"llm": llm, "asr": asr}


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
        mode = patch.pop("mode", None)
        if mode is not None and mode not in ASR_MODES:
            raise HTTPException(
                status_code=400,
                detail=i18n.t(
                    "asr.invalid_mode", mode=mode, available=", ".join(ASR_MODES)
                ),
            )
        engine = patch.pop("engine", None)
        if engine and engine not in engines_mod.available_engines():
            raise HTTPException(
                status_code=400,
                detail=i18n.t(
                    "engine.unsupported",
                    name=engine,
                    available=", ".join(engines_mod.available_engines()),
                ),
            )
        if "cloud_api_key" in patch and not (patch["cloud_api_key"] or "").strip():
            patch.pop("cloud_api_key")  # empty key keeps the stored one
        stored = db.get_setting(conn, "asr")
        base = (
            {k: stored[k] for k in _ASR_STORED_KEYS if k in stored}
            if isinstance(stored, dict)
            else {}
        )
        merged = {**base, **patch}
        if mode is not None:
            merged["mode"] = mode
        # A mode change re-engines the manager BEFORE anything is
        # persisted: a busy engine 409s and the stored mode stays as-is.
        if mode is not None and mode != (current["asr"].get("mode") or "local"):
            target = (
                "cloud" if mode == "cloud" else engines_mod.local_engine()
            )
            try:
                result = await request.app.state.engine_manager.switch(target)
            except EngineError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if result.get("busy"):
                raise HTTPException(
                    status_code=409, detail=result.get("detail")
                )
        db.set_setting(conn, "asr", merged)

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
            "message": i18n.t("llm.no_key"),
        }
    ok, message = await llm_mod.test_connection(cfg)
    return {"ok": ok, "message": message}
