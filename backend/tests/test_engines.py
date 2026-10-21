"""Task B9 tests: dual ASR engine manager + adapter mappings (spec §7)."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services import engines
from app.services.engines import EngineError, EngineManager


class FakeEngine:
    name = "fake"

    def __init__(self, engine_name):
        self.engine_name = engine_name
        self.unloaded = False

    def transcribe(self, path):
        return [{"w": "hello", "s": 0.0, "e": 0.5, "p": 0.9}]


def make_manager(settings=None, factory=None, sleep_fn=None):
    events = []
    settings = settings or {
        "engine": "parakeet",
        "parakeet_model": "p-model",
        "whisper_model": "w-model",
        "idle_unload_min": 10,
    }

    def default_factory(engine_name, model):
        events.append(("load", engine_name, model))
        return FakeEngine(engine_name)

    mgr = EngineManager(
        factory=factory or default_factory,
        settings_fn=lambda: settings,
        sleep_fn=sleep_fn,
        on_unload=lambda eng: events.append(("unload", eng.engine_name)),
        on_switch=lambda name: events.append(("switch", name)),
    )
    return mgr, events, settings


@pytest.mark.asyncio
async def test_lazy_load_and_unload():
    mgr, events, _ = make_manager()
    assert mgr.status()["state"] == "unloaded"
    assert events == []  # nothing loaded until first use

    eng = await mgr.acquire()
    assert mgr.status()["state"] == "ready"
    assert events == [("load", "parakeet", "p-model")]
    await mgr.release()
    st = mgr.status()
    assert st["state"] == "ready"  # still loaded, idle timer pending
    assert st["last_used"] is not None

    result = await mgr.unload_now()
    assert result["state"] == "unloaded"
    assert ("unload", "parakeet") in events

    # next acquire reloads
    await mgr.acquire()
    await mgr.release()
    await mgr.unload_now()
    assert events.count(("load", "parakeet", "p-model")) == 2


@pytest.mark.asyncio
async def test_switch_unloads_current():
    mgr, events, settings = make_manager()
    await mgr.acquire()
    await mgr.release()
    await mgr.switch("whisper")
    assert ("unload", "parakeet") in events
    assert ("switch", "whisper") in events
    st = mgr.status()
    assert st["state"] == "unloaded"
    assert st["engine"] == "whisper"
    # next transcription loads the NEW engine
    eng = await mgr.acquire()
    assert eng.engine_name == "whisper"
    await mgr.release()
    await mgr.unload_now()


@pytest.mark.asyncio
async def test_busy_rejects_unload_during_transcribe():
    mgr, events, _ = make_manager()
    await mgr.acquire()  # transcription in flight (no release yet)
    busy = await mgr.unload_now()
    assert busy["state"] == "ready"
    assert "busy" in (busy.get("detail") or "").lower() or busy.get("busy")
    busy_switch = await mgr.switch("whisper")
    assert "busy" in (busy_switch.get("detail") or "").lower() or busy_switch.get("busy")
    assert mgr.status()["engine"] == "parakeet"  # unchanged
    await mgr.release()
    ok = await mgr.unload_now()
    assert ok["state"] == "unloaded"


@pytest.mark.asyncio
async def test_second_acquire_waits_for_release():
    mgr, _, _ = make_manager()

    async def slow_user():
        eng = await mgr.acquire()
        await asyncio.sleep(0.05)
        await mgr.release()
        return eng

    async def queued_user():
        eng = await mgr.acquire()
        await mgr.release()
        return eng

    results = await asyncio.gather(slow_user(), queued_user())
    assert all(r.engine_name == "parakeet" for r in results)


@pytest.mark.asyncio
async def test_idle_timer_unloads():
    async def fast_sleep(seconds):
        return None  # pretend the idle delay elapsed instantly

    mgr, events, settings = make_manager(sleep_fn=fast_sleep)
    settings["idle_unload_min"] = 1
    await mgr.acquire()
    await mgr.release()
    for _ in range(20):
        await asyncio.sleep(0)
    assert mgr.status()["state"] == "unloaded"
    assert ("unload", "parakeet") in events


@pytest.mark.asyncio
async def test_idle_timer_disabled_with_zero():
    async def fast_sleep(seconds):
        return None

    mgr, _, settings = make_manager(sleep_fn=fast_sleep)
    settings["idle_unload_min"] = 0
    await mgr.acquire()
    await mgr.release()
    for _ in range(10):
        await asyncio.sleep(0)
    assert mgr.status()["state"] == "ready"


@pytest.mark.asyncio
async def test_load_failure_sets_error_and_recovers():
    def flaky_factory(engine_name, model):
        if engine_name == "parakeet":
            raise RuntimeError("mlx not available")
        return FakeEngine(engine_name)

    mgr, _, settings = make_manager(factory=flaky_factory)
    with pytest.raises(EngineError):
        await mgr.acquire()
    st = mgr.status()
    assert st["state"] == "error"
    assert "mlx not available" in (st.get("detail") or "")

    await mgr.switch("whisper")
    eng = await mgr.acquire()  # other engine unaffected
    assert eng.engine_name == "whisper"
    await mgr.release()
    await mgr.unload_now()


# ---------------- adapter mapping tests (no real MLX needed) ----------------

def test_parakeet_result_mapping():
    from app.services.parakeet_engine import result_to_words

    tok = lambda t, s, e: SimpleNamespace(text=t, start=s, end=e)
    result = SimpleNamespace(
        segments=[
            SimpleNamespace(tokens=[tok("Hello", 0.0, 0.4), tok("there.", 0.4, 0.7)]),
            SimpleNamespace(tokens=[tok("World", 0.8, 1.1)]),
        ]
    )
    words = result_to_words(result)
    assert words == [
        {"w": "Hello", "s": 0.0, "e": 0.4},
        {"w": "there.", "s": 0.4, "e": 0.7},
        {"w": "World", "s": 0.8, "e": 1.1},
    ]


def test_parakeet_flat_tokens_mapping():
    from app.services.parakeet_engine import result_to_words

    result = SimpleNamespace(
        tokens=[SimpleNamespace(text="one", start=0.1, end=0.2),
                SimpleNamespace(text="two", start=0.3, end=0.4)]
    )
    assert [w["w"] for w in result_to_words(result)] == ["one", "two"]


def test_whisper_result_mapping():
    from app.services.whisper_engine import result_to_words

    result = {
        "segments": [
            {
                "words": [
                    {"word": " Hello", "start": 0.0, "end": 0.3,
                     "probability": 0.98},
                    {"word": " there", "start": 0.3, "end": 0.6,
                     "probability": 0.91},
                ]
            },
            {"words": [{"word": " world", "start": 0.7, "end": 1.0,
                        "probability": 0.85}]},
        ]
    }
    words = result_to_words(result)
    assert words[0] == {"w": "Hello", "s": 0.0, "e": 0.3, "p": 0.98}
    assert [w["w"] for w in words] == ["Hello", "there", "world"]
    assert all(0.0 <= w["p"] <= 1.0 for w in words)


def test_engines_module_importable_without_mlx():
    # importing the manager must never pull MLX (Windows CI constraint)
    import sys

    assert "mlx_whisper" not in sys.modules
    assert "parakeet_mlx" not in sys.modules
    assert hasattr(engines, "manager")
