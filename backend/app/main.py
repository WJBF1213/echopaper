"""FastAPI application factory (Task B12).

Serves /api/* per design spec §8 and, when frontend/dist exists, hosts it
at "/" via StaticFiles(html=True) AFTER the API routes. With no dist (the
normal state — the frontend is built externally), "/" returns a JSON hint
instead of crashing.

python -m app.main starts uvicorn on 127.0.0.1:8300.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import REPO_ROOT, load_settings
from app.routers import (
    asr as asr_router,
    attempts as attempts_router,
    health as health_router,
    materials as materials_router,
    review as review_router,
    sets as sets_router,
    settings as settings_router,
    translate as translate_router,
)
from app.services import engines, jobs as jobs_svc, translate_svc

VERSION = "1.0.0"


def create_app(
    conn=None,
    data_dir: Path | None = None,
    dist_dir: Path | None = None,
    engine_manager=None,
    jobs_manager=None,
) -> FastAPI:
    settings = load_settings()
    data_dir = Path(data_dir or settings.data_dir)
    dist_dir = Path(dist_dir) if dist_dir is not None else REPO_ROOT / "frontend" / "dist"

    own_conn = conn is None
    if own_conn:
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(data_dir / "app.db")
        db.init_db(conn)

    from app.routers.settings import effective_settings

    engine_manager = engine_manager or engines.manager
    jobs_manager = jobs_manager or jobs_svc.jobs

    def asr_settings() -> dict:
        try:
            return effective_settings(conn)["asr"]
        except Exception:
            return {}

    def persist_engine(name: str) -> None:
        current = asr_settings()
        current["engine"] = name
        db.set_setting(conn, "asr", current)

    engine_manager.configure(
        settings_fn=asr_settings, on_switch=persist_engine
    )

    def llm_cfg():
        try:
            from app.routers.settings import llm_cfg_or_none

            return llm_cfg_or_none(effective_settings(conn))
        except Exception:
            return None

    jobs_manager.configure(
        conn=conn,
        engine_manager=engine_manager,
        llm_cfg_fn=llm_cfg,
        data_dir=data_dir,
    )
    translate_svc.configure(conn)

    app = FastAPI(
        title="雅思听力挖空练习",
        version=VERSION,
        # single-user local app: show docs locally for convenience
        docs_url="/docs",
    )
    app.state.conn = conn
    app.state.data_dir = data_dir
    app.state.engine_manager = engine_manager
    app.state.jobs_manager = jobs_manager
    app.state.own_conn = own_conn

    app.include_router(health_router.router, prefix="/api")
    app.include_router(settings_router.router, prefix="/api")
    app.include_router(asr_router.router, prefix="/api")
    app.include_router(materials_router.router, prefix="/api")
    app.include_router(sets_router.router, prefix="/api")
    app.include_router(attempts_router.router, prefix="/api")
    app.include_router(review_router.router, prefix="/api")
    app.include_router(translate_router.router, prefix="/api")

    # static hosting AFTER api routes (spec: hash router SPA if present)
    if dist_dir.is_dir():
        app.mount(
            "/", StaticFiles(directory=str(dist_dir), html=True), name="static"
        )
    else:

        @app.get("/")
        def frontend_hint():  # pragma: no cover - trivial
            return {
                "hint": "前端构建产物不存在（frontend/dist）。后端 API 正常运行："
                        "/docs、/api/health。前端由外部实现，接口契约见设计文档 §8。",
                "ok": True,
                "version": VERSION,
            }

    return app


if __name__ == "__main__":  # pragma: no cover - manual launch path
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=settings.port,
        log_level="info",
    )
