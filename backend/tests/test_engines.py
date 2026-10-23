"""Task B9 tests: ASR engine manager + adapter mappings (spec §7)."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import engines
from app.services.engines import EngineError, EngineManager


@pytest.fixture(autouse=True)
def parakeet_host(request, monkeypatch):
    """Manager tests run as if on Apple Silicon (both local engines).

    The engine is platform-derived, so tests pin ``local_engine`` to
    parakeet and expose every engine. Tests that assert real platform
    detection opt out with ``@pytest.mark.real_platform``.
    """
    if request.node.get_closest_marker("real_platform"):
        return
    monkeypatch.setattr(engines, "available_engines", lambda *a, **k: engines.ENGINE_NAMES)
    monkeypatch.setattr(engines, "local_engine", lambda *a, **k: "parakeet")


class FakeEngine:
    name = "fake"

    def __init__(self, engine_name):
        self.engine_name = engine_name
        self.unloaded = False

    def transcribe(self, path):
        return [{"w": "hello", "s": 0.0, "e": 0.5, "p": 0.9}]


def make_manager(settings=None, factory=None, sleep_fn=None):
    events = []
    settings = settings or {"idle_unload_min": 10}

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


# ---------------- module surface: one engine+model per platform ----------------

def test_engine_names_are_exactly_the_two_local_engines():
    assert engines.ENGINE_NAMES == ("parakeet", "faster_whisper")
    assert "whisper" not in engines.ENGINE_NAMES


def test_fixed_model_constants():
    assert engines.PARAKEET_MODEL == "mlx-community/parakeet-tdt-0.6b-v3"
    assert engines.FASTER_WHISPER_MODEL == "large-v3-turbo"


@pytest.mark.real_platform
def test_local_engine_and_availability_apple_silicon():
    assert engines.available_engines("darwin", "arm64") == engines.ENGINE_NAMES
    assert engines.local_engine("darwin", "arm64") == "parakeet"


@pytest.mark.real_platform
def test_local_engine_and_availability_other_platforms():
    # Intel Macs and every non-darwin platform only get CTranslate2.
    for platform_name, machine in (
        ("darwin", "x86_64"),
        ("win32", "AMD64"),
        ("linux", "x86_64"),
    ):
        assert engines.available_engines(platform_name, machine) == (
            engines.FALLBACK_ENGINE,
        )
        assert engines.local_engine(platform_name, machine) == (
            engines.FALLBACK_ENGINE
        )


# ---------------- lifecycle ----------------

@pytest.mark.asyncio
async def test_lazy_load_and_unload():
    mgr, events, _ = make_manager()
    assert mgr.status()["state"] == "unloaded"
    assert events == []  # nothing loaded until first use

    eng = await mgr.acquire()
    assert mgr.status()["state"] == "ready"
    assert events == [("load", "parakeet", engines.PARAKEET_MODEL)]
    await mgr.release()
    st = mgr.status()
    assert st["state"] == "ready"  # still loaded, idle timer pending
    assert st["engine"] == "parakeet"
    assert st["model"] == engines.PARAKEET_MODEL
    assert st["last_used"] is not None

    result = await mgr.unload_now()
    assert result["state"] == "unloaded"
    assert ("unload", "parakeet") in events

    # next acquire reloads
    await mgr.acquire()
    await mgr.release()
    await mgr.unload_now()
    assert events.count(("load", "parakeet", engines.PARAKEET_MODEL)) == 2


@pytest.mark.asyncio
async def test_legacy_settings_engine_and_models_are_ignored():
    """A stored row from the three-engine era must not select anything."""
    mgr, events, _ = make_manager()
    mgr._settings_fn = lambda: {
        "engine": "whisper",
        "whisper_model": "legacy",
        "parakeet_model": "legacy",
        "faster_whisper_model": "legacy",
        "idle_unload_min": 10,
    }
    eng = await mgr.acquire()
    assert eng.engine_name == "parakeet"  # platform-derived
    assert events[-1] == ("load", "parakeet", engines.PARAKEET_MODEL)
    await mgr.release()
    await mgr.unload_now()


@pytest.mark.asyncio
async def test_switch_unloads_current():
    mgr, events, settings = make_manager()
    await mgr.acquire()
    await mgr.release()
    await mgr.switch("faster_whisper")
    assert ("unload", "parakeet") in events
    assert ("switch", "faster_whisper") in events
    st = mgr.status()
    assert st["state"] == "unloaded"
    assert st["engine"] == "faster_whisper"
    assert st["model"] == engines.FASTER_WHISPER_MODEL
    # next transcription loads the NEW engine
    eng = await mgr.acquire()
    assert eng.engine_name == "faster_whisper"
    await mgr.release()
    await mgr.unload_now()


@pytest.mark.asyncio
async def test_busy_rejects_unload_during_transcribe():
    mgr, events, _ = make_manager()
    await mgr.acquire()  # transcription in flight (no release yet)
    busy = await mgr.unload_now()
    assert busy["state"] == "ready"
    assert "busy" in (busy.get("detail") or "").lower() or busy.get("busy")
    busy_switch = await mgr.switch("faster_whisper")
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

    await mgr.switch("faster_whisper")
    eng = await mgr.acquire()  # other engine unaffected
    assert eng.engine_name == "faster_whisper"
    await mgr.release()
    await mgr.unload_now()


@pytest.mark.asyncio
async def test_switch_to_unavailable_engine_rejected(monkeypatch):
    monkeypatch.setattr(
        engines, "available_engines", lambda *a, **k: (engines.FALLBACK_ENGINE,)
    )
    mgr, _, _ = make_manager()
    with pytest.raises(EngineError):
        await mgr.switch("parakeet")


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


def test_faster_whisper_result_mapping():
    from app.services.faster_whisper_engine import result_to_words

    segments = [
        SimpleNamespace(words=[
            SimpleNamespace(word=" Hello", start=0.0, end=0.3,
                            probability=0.98),
            SimpleNamespace(word=" there", start=0.3, end=0.6,
                            probability=0.91),
        ]),
        SimpleNamespace(words=[
            SimpleNamespace(word=" world", start=0.7, end=1.0,
                            probability=0.85),
        ]),
    ]
    words = result_to_words(segments)
    assert words == [
        {"w": "Hello", "s": 0.0, "e": 0.3, "p": 0.98},
        {"w": "there", "s": 0.3, "e": 0.6, "p": 0.91},
        {"w": "world", "s": 0.7, "e": 1.0, "p": 0.85},
    ]


def test_faster_whisper_result_mapping_edge_cases():
    """Generators, missing word lists, blank words and absent probability."""
    from app.services.faster_whisper_engine import result_to_words

    segments = (
        SimpleNamespace(words=[
            SimpleNamespace(word="   ", start=0.0, end=0.1, probability=0.5),
            SimpleNamespace(word="ok", start=0.1, end=0.2),  # no probability
        ]),
        SimpleNamespace(words=None),
        SimpleNamespace(),  # no words attribute at all
    )
    assert result_to_words(segments) == [
        {"w": "ok", "s": 0.1, "e": 0.2},
    ]

    from app.services.faster_whisper_engine import FasterWhisperEngine

    assert FasterWhisperEngine.name == "faster_whisper"


def test_engines_module_importable_without_mlx():
    # importing the manager must never pull MLX (Windows CI constraint)
    import sys

    assert "parakeet_mlx" not in sys.modules
    assert hasattr(engines, "manager")


def test_importing_engines_stays_lazy_for_faster_whisper():
    """Import isolation cannot be proven in-process once other tests have
    imported the adapter, so run a clean interpreter."""
    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "import app.services.engines as engines\n"
        "assert hasattr(engines, 'manager')\n"
        "assert 'faster_whisper' not in sys.modules\n"
        "assert 'app.services.faster_whisper_engine' not in sys.modules\n"
        "assert 'ctranslate2' not in sys.modules\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend_dir) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
