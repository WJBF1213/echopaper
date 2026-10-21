"""ASR engine lifecycle manager (Task B9, spec §7).

Dual engines (parakeet-mlx / mlx-whisper) are equal first-class citizens.
Lazy load on first transcription, idle auto-unload with gc, immediate
unload on switch. One asyncio lock serializes lifecycle operations; a
semaphore serializes transcriptions (acquire..release). Busy -> unload /
switch are REJECTED, never deadlock. MLX imports happen only inside the
concrete engine constructors (lazy), so this module imports cleanly on
any platform.

Stdlib + engines only; no framework imports.
"""
from __future__ import annotations

import asyncio
import gc
import time
from typing import Any, Callable, Protocol

ENGINE_NAMES = ("parakeet", "whisper")


class EngineError(Exception):
    """Engine load/transcription setup failure."""


class AsrEngine(Protocol):
    name: str

    def transcribe(self, path: str) -> list[dict]: ...


def default_factory(engine_name: str, model: str) -> Any:
    """Construct an engine, importing its MLX deps lazily (darwin only)."""
    if engine_name == "parakeet":
        from app.services.parakeet_engine import ParakeetEngine

        return ParakeetEngine(model)
    if engine_name == "whisper":
        from app.services.whisper_engine import WhisperEngine

        return WhisperEngine(model)
    raise EngineError(f"未知引擎：{engine_name}")


DEFAULT_SETTINGS: dict[str, Any] = {
    "engine": "parakeet",
    "parakeet_model": "mlx-community/parakeet-tdt-0.6b-v3",
    "whisper_model": "mlx-community/whisper-large-v3-turbo",
    "idle_unload_min": 10,
}


class EngineManager:
    def __init__(
        self,
        factory: Callable[[str, str], Any] | None = None,
        settings_fn: Callable[[], dict] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
        on_unload: Callable[[Any], None] | None = None,
        on_switch: Callable[[str], None] | None = None,
    ):
        self._factory = factory or default_factory
        self._settings_fn = settings_fn or (lambda: dict(DEFAULT_SETTINGS))
        self._sleep = sleep_fn or asyncio.sleep
        self._on_unload = on_unload or (lambda eng: None)
        self._on_switch = on_switch or (lambda name: None)

        self._engine: Any = None
        self._loaded_name: str | None = None
        self._engine_name: str | None = None  # selected (persisted via hook)
        self._lock = asyncio.Lock()  # lifecycle: load/unload/switch
        self._gate = asyncio.Semaphore(1)  # one transcription at a time
        self._busy = False
        self._state = "unloaded"  # unloaded | loading | ready | error
        self._detail: str | None = None
        self._last_used: float | None = None
        self._timer: asyncio.Task | None = None

    # ------------------------------------------------------------------ util
    def _settings(self) -> dict:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self._settings_fn() or {})
        return merged

    def _current_name(self) -> str:
        if self._engine_name is None:
            self._engine_name = self._settings().get("engine", "parakeet")
        return self._engine_name

    def status(self) -> dict:
        name = self._current_name()
        s = self._settings()
        out: dict = {
            "state": self._state,
            "engine": name,
            "model": s.get(f"{name}_model", ""),
            "idle_unload_min": s.get("idle_unload_min", 10),
        }
        if self._last_used is not None:
            out["last_used"] = self._last_used
        if self._detail:
            out["detail"] = self._detail
        return out

    # -------------------------------------------------------------- lifecycle
    async def _load_locked(self, engine_name: str) -> Any:
        self._cancel_timer()
        self._state = "loading"
        self._detail = None
        model = self._settings().get(f"{engine_name}_model", "")
        try:
            engine = await asyncio.to_thread(self._factory, engine_name, model)
        except Exception as exc:
            self._engine = None
            self._loaded_name = None
            self._state = "error"
            self._detail = (
                f"{engine_name} 引擎加载失败：{exc}；请在设置页更换引擎或模型"
            )
            raise EngineError(self._detail) from exc
        self._engine = engine
        self._loaded_name = engine_name
        self._state = "ready"
        return engine

    def _drop_locked(self) -> None:
        engine = self._engine
        self._engine = None
        self._loaded_name = None
        self._state = "unloaded"
        self._detail = None
        if engine is not None:
            try:
                self._on_unload(engine)
            except Exception:
                pass
        gc.collect()

    def _cancel_timer(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    def _schedule_idle_timer(self) -> None:
        self._cancel_timer()
        try:
            idle_min = int(self._settings().get("idle_unload_min", 10) or 0)
        except (TypeError, ValueError):
            idle_min = 0
        if idle_min <= 0:
            return
        self._timer = asyncio.create_task(self._idle_fire(idle_min * 60))

    async def _idle_fire(self, delay_s: float) -> None:
        await self._sleep(delay_s)
        async with self._lock:
            if not self._busy and self._engine is not None:
                self._drop_locked()

    # ---------------------------------------------------------------- public
    async def acquire(self) -> Any:
        """Ensure the current engine is loaded, then hold it for one job.

        Concurrent acquires queue on the gate until the previous release().
        """
        async with self._lock:
            engine_name = self._current_name()
            if self._engine is None or self._loaded_name != engine_name:
                if self._busy:
                    raise EngineError("引擎选择已变更，请等待当前转写完成")
                await self._load_locked(engine_name)
        await self._gate.acquire()
        self._busy = True
        self._last_used = time.time()
        if self._engine is None:  # unloaded between lock and gate
            self._busy = False
            self._gate.release()
            raise EngineError("引擎已被卸载，请重试")
        return self._engine

    async def release(self) -> None:
        self._busy = False
        self._last_used = time.time()
        try:
            self._gate.release()
        except ValueError:
            pass
        self._schedule_idle_timer()

    async def unload_now(self) -> dict:
        """Manual immediate unload; rejected (busy) during transcription."""
        async with self._lock:
            if self._busy:
                return {**self.status(), "busy": True,
                        "detail": "busy：转写进行中，禁止卸载"}
            self._cancel_timer()
            self._drop_locked()
            return self.status()

    async def switch(self, engine_name: str) -> dict:
        """Switch engine: unload current immediately; busy -> reject."""
        if engine_name not in ENGINE_NAMES:
            raise EngineError(f"未知引擎：{engine_name}")
        async with self._lock:
            if self._busy:
                return {**self.status(), "busy": True,
                        "detail": "busy：转写进行中，禁止切换"}
            self._cancel_timer()
            if self._engine is not None:
                self._drop_locked()
            self._engine_name = engine_name
            try:
                self._on_switch(engine_name)
            except Exception:
                pass
            return self.status()


#: process-wide singleton; main wires its hooks at startup (B12)
manager = EngineManager()
