"""Cloud transcription engine tests (Task 3).

Covers:
- ``audio.prepare_upload_audio``: pass-through, 16 kHz mono MP3
  recompression (probed with PyAV), ~N-minute chunking with offsets
- ``words_from_verbose_json``: exact word mapping + segment-only fallback
- ``CloudEngine.transcribe``: OpenAI-compatible multipart contract,
  2-retry policy (429/5xx/transport), RuntimeError carrying the provider
  status/body, per-chunk offsets and temp cleanup
- ``test_cloud_connection``: GET {base}/models probe outcomes
- cloud lifecycle in ``EngineManager``: no-op load, no idle timer,
  switch unloads the local model, configure derives the mode

No network: the httpx client is always injected (fake, test_llm.py
pattern); keys/URLs are fake.
"""
import json
import math
import struct
import wave
from pathlib import Path

import httpx
import pytest

from app.services import audio, engines
from app.services.cloud_engine import (
    CloudEngine,
    words_from_verbose_json,
)
from app.services.cloud_engine import test_cloud_connection as cloud_probe
from app.services.engines import EngineManager

CFG = {
    "cloud_base_url": "https://fake.example/v1",
    "cloud_model": "whisper-large-v3-turbo",
    "cloud_api_key": "sk-test",
}

VERBOSE = {
    "segments": [
        {
            "words": [
                {"word": " Hello", "start": 0.0, "end": 0.4},
                {"word": " world", "start": 0.4, "end": 0.9},
            ]
        },
    ]
}


def write_wav(path: Path, seconds: float, rate: int = 44100,
              channels: int = 2) -> Path:
    n = int(rate * seconds)
    buf = bytearray()
    for i in range(n):
        v = int(11000 * math.sin(i * 0.031))
        if channels == 2:
            buf += struct.pack("<hh", v, -v)
        else:
            buf += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(buf))
    return path


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text or (
            json.dumps(payload) if payload is not None else ""
        )

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeHttpClient:
    """Sync httpx.Client stand-in: records POSTs, replies from a queue."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class FakeAsyncClient:
    """Async httpx.AsyncClient stand-in for the /models probe."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def aclose(self):
        pass


def make_engine(settings=None, client_replies=None):
    settings = dict(CFG) if settings is None else dict(settings)
    engine = CloudEngine(settings_fn=lambda: settings, backoff_s=(0, 0))
    client = FakeHttpClient(client_replies or [FakeResponse(VERBOSE)])
    return engine, client


# ---------------- prepare_upload_audio ----------------


def test_prepare_small_file_passes_through(tmp_path):
    wav = write_wav(tmp_path / "small.wav", 0.2)
    out = audio.prepare_upload_audio(str(wav))
    assert out == [(str(wav), 0.0)]


def test_prepare_recompresses_to_16k_mono_mp3(tmp_path):
    import av

    wav = write_wav(tmp_path / "big.wav", 1.0)  # ~176 KB stereo WAV
    try:
        out = audio.prepare_upload_audio(str(wav), threshold_mb=0.0001)
        assert len(out) == 1  # 1 s < one chunk window
        path, offset = out[0]
        assert offset == 0.0
        assert path != str(wav)
        assert Path(path).suffix == ".mp3"
        assert Path(path).stat().st_size < wav.stat().st_size
        with av.open(path) as container:
            frames = list(container.decode(audio=0))
        assert frames
        assert {f.sample_rate for f in frames} == {16000}
        assert {f.layout.name for f in frames} == {"mono"}
    finally:  # the caller owns temp cleanup (Task 3 contract)
        for path, _ in out:
            Path(path).unlink(missing_ok=True)


def test_prepare_chunks_when_recompress_still_exceeds(tmp_path):
    import av

    wav = write_wav(tmp_path / "long.wav", 3.0, rate=16000, channels=1)
    try:
        out = audio.prepare_upload_audio(
            str(wav), threshold_mb=0.0001, chunk_seconds=1.5
        )
        assert len(out) >= 2
        offsets = [off for _, off in out]
        assert offsets[0] == 0.0
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets)  # strictly increasing
        total = 0.0
        last = None
        for path, _ in out:
            with av.open(path) as container:
                dur = sum(
                    f.samples for f in container.decode(audio=0)
                ) / 16000.0
            total += dur
            last = (path, dur)
        # chunk durations sum back to the original duration
        assert abs(total - 3.0) < 0.2
        # and the final offset + final chunk duration lands on the end
        assert abs((offsets[-1] + last[1]) - 3.0) < 0.2
    finally:
        for path, _ in out:
            Path(path).unlink(missing_ok=True)


def test_chunk_window_default_is_ten_minutes():
    assert audio.CHUNK_SECONDS == 600.0


# ---------------- verbose_json parsing ----------------


def test_words_from_verbose_json_exact_mapping():
    payload = {
        "segments": [
            {
                "words": [
                    {"word": " The", "start": 0.0, "end": 0.2},
                    {"word": "cat", "start": 0.2, "end": 0.5},
                ]
            },
            {"words": [{"word": "sat.", "start": 0.6, "end": 0.9}]},
        ]
    }
    assert words_from_verbose_json(payload) == [
        {"w": "The", "s": 0.0, "e": 0.2},
        {"w": "cat", "s": 0.2, "e": 0.5},
        {"w": "sat.", "s": 0.6, "e": 0.9},
    ]


def test_words_from_segment_only_payload_expands_evenly():
    payload = {
        "segments": [{"text": "hello there friend", "start": 1.0, "end": 2.5}]
    }
    words = words_from_verbose_json(payload)
    assert [w["w"] for w in words] == ["hello", "there", "friend"]
    stamps = [w["s"] for w in words] + [words[-1]["e"]]
    assert stamps == sorted(stamps)  # monotonic within the segment
    assert all(1.0 <= w["s"] <= 2.5 for w in words)
    assert all(1.0 <= w["e"] <= 2.5 for w in words)
    assert words[0]["s"] == 1.0
    assert words[-1]["e"] == 2.5


def test_words_from_empty_payload():
    assert words_from_verbose_json({}) == []
    assert words_from_verbose_json({"segments": []}) == []
    assert words_from_verbose_json(
        {"segments": [{"text": "  ", "start": 0.0, "end": 1.0}]}
    ) == []


# ---------------- CloudEngine.transcribe (mocked httpx) ----------------


def test_transcribe_success_openai_contract(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 0.2)
    engine, client = make_engine()
    words = engine.transcribe(str(wav), client=client)
    assert words == [
        {"w": "Hello", "s": 0.0, "e": 0.4},
        {"w": "world", "s": 0.4, "e": 0.9},
    ]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://fake.example/v1/audio/transcriptions"
    data = call["data"]
    assert data["model"] == "whisper-large-v3-turbo"
    assert data["response_format"] == "verbose_json"
    assert data["timestamp_granularities[]"] == "word"
    assert data["language"] == "en"
    assert "Bearer sk-test" in call["headers"]["Authorization"]
    # under threshold: the ORIGINAL file is uploaded
    assert call["files"]["file"][0] == "a.wav"


def test_transcribe_reads_settings_at_call_time(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 0.2)
    settings = dict(CFG)
    engine = CloudEngine(settings_fn=lambda: settings, backoff_s=(0, 0))
    first = FakeHttpClient([FakeResponse(VERBOSE)])
    engine.transcribe(str(wav), client=first)
    settings["cloud_api_key"] = "sk-rotated"
    settings["cloud_base_url"] = "https://other.example/v1"
    second = FakeHttpClient([FakeResponse(VERBOSE)])
    engine.transcribe(str(wav), client=second)
    assert "Bearer sk-test" in first.calls[0]["headers"]["Authorization"]
    assert "Bearer sk-rotated" in second.calls[0]["headers"]["Authorization"]
    assert second.calls[0]["url"].startswith("https://other.example/v1/")


def test_transcribe_retries_429_then_succeeds(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 0.2)
    engine, client = make_engine(client_replies=[
        FakeResponse(status=429, text="rate limited"),
        FakeResponse(status=500, text="server exploded"),
        FakeResponse(VERBOSE),
    ])
    words = engine.transcribe(str(wav), client=client)
    assert words  # third attempt wins
    assert len(client.calls) == 3


def test_transcribe_401_no_retry_runtime_error_carries_body(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 0.2)
    engine, client = make_engine(client_replies=[
        FakeResponse(status=401, text='{"error":{"message":"Invalid key"}}')
    ])
    with pytest.raises(RuntimeError) as excinfo:
        engine.transcribe(str(wav), client=client)
    assert "401" in str(excinfo.value)
    assert "Invalid key" in str(excinfo.value)
    assert len(client.calls) == 1  # client errors are not retried


def test_transcribe_transport_error_retried_then_runtime_error(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 0.2)
    engine, client = make_engine(client_replies=[
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
    ])
    with pytest.raises(RuntimeError) as excinfo:
        engine.transcribe(str(wav), client=client)
    assert "boom" in str(excinfo.value)
    assert len(client.calls) == 3  # 1 try + 2 retries


def test_transcribe_without_key_raises(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 0.2)
    engine = CloudEngine(
        settings_fn=lambda: {"cloud_api_key": ""}, backoff_s=(0, 0)
    )
    with pytest.raises(RuntimeError) as excinfo:
        engine.transcribe(str(wav))
    assert "API key" in str(excinfo.value)


def test_transcribe_chunks_apply_offsets_and_clean_up(tmp_path, monkeypatch):
    from app.services import cloud_engine

    wav = write_wav(tmp_path / "a.wav", 0.2)
    c1 = tmp_path / "chunk-0.mp3"
    c1.write_bytes(b"fake-1")
    c2 = tmp_path / "chunk-1.mp3"
    c2.write_bytes(b"fake-2")
    monkeypatch.setattr(
        cloud_engine.audio_mod,
        "prepare_upload_audio",
        lambda path, **kw: [(str(c1), 0.0), (str(c2), 100.0)],
    )
    payload1 = {
        "segments": [{"words": [{"word": "one", "start": 0.1, "end": 0.2}]}]
    }
    payload2 = {
        "segments": [{"words": [{"word": "two", "start": 0.3, "end": 0.5}]}]
    }
    engine, client = make_engine(
        client_replies=[FakeResponse(payload1), FakeResponse(payload2)]
    )
    words = engine.transcribe(str(wav), client=client)
    assert words == [
        {"w": "one", "s": 0.1, "e": 0.2},
        {"w": "two", "s": 100.3, "e": 100.5},
    ]
    assert len(client.calls) == 2
    # chunk temps removed; the original audio untouched
    assert not c1.exists()
    assert not c2.exists()
    assert wav.exists()


# ---------------- test_cloud_connection (GET /models) ----------------


@pytest.mark.asyncio
async def test_cloud_connection_ok_model_listed():
    reply = FakeResponse(
        {"data": [{"id": "whisper-large-v3-turbo"}, {"id": "other"}]}
    )
    client = FakeAsyncClient(reply)
    ok, message = await cloud_probe(CFG, client=client)
    assert ok is True
    assert message
    assert client.calls[0]["url"] == "https://fake.example/v1/models"
    assert (
        "Bearer sk-test" in client.calls[0]["headers"]["Authorization"]
    )


@pytest.mark.asyncio
async def test_cloud_connection_model_missing_notes_it():
    reply = FakeResponse({"data": [{"id": "something-else"}]})
    ok, message = await cloud_probe(CFG, client=FakeAsyncClient(reply))
    assert ok is True
    assert "whisper-large-v3-turbo" in message


@pytest.mark.asyncio
async def test_cloud_connection_key_invalid():
    reply = FakeResponse({"error": "bad key"}, status=401)
    ok, message = await cloud_probe(
        CFG, client=FakeAsyncClient(reply)
    )
    assert ok is False
    assert "401" in message


@pytest.mark.asyncio
async def test_cloud_connection_unreachable():
    ok, message = await cloud_probe(
        CFG, client=FakeAsyncClient(httpx.ConnectError("no route"))
    )
    assert ok is False
    assert message


@pytest.mark.asyncio
async def test_cloud_connection_no_key():
    ok, message = await cloud_probe(
        {"cloud_api_key": ""}, client=FakeAsyncClient(None)
    )
    assert ok is False
    assert "API key" in message


# ---------------- EngineManager cloud lifecycle ----------------


class FakeLocalEngine:
    def __init__(self, name):
        self.name = name

    def transcribe(self, path):
        return []


def test_cloud_registered_on_all_platforms():
    assert engines.ENGINE_NAMES == (
        "parakeet", "faster_whisper", "cloud"
    )
    for platform_name, machine in (
        ("darwin", "arm64"),
        ("darwin", "x86_64"),
        ("win32", "AMD64"),
        ("linux", "x86_64"),
    ):
        avail = engines.available_engines(platform_name, machine)
        assert "cloud" in avail
        assert engines.local_engine(platform_name, machine) in avail


@pytest.mark.asyncio
async def test_switch_to_cloud_unloads_local_model():
    loads, unloads = [], []

    def factory(name, model):
        loads.append(name)
        return FakeLocalEngine(name)

    mgr = EngineManager(
        factory=factory, on_unload=lambda eng: unloads.append(eng.name)
    )
    await mgr.acquire()
    await mgr.release()
    assert loads
    result = await mgr.switch("cloud")
    assert unloads
    assert result["engine"] == "cloud"


@pytest.mark.asyncio
async def test_cloud_acquire_is_noop_load_without_idle_timer():
    def factory(name, model):
        raise AssertionError("cloud must not load a local model")

    mgr = EngineManager(
        factory=factory, settings_fn=lambda: {"mode": "cloud"}
    )
    await mgr.switch("cloud")
    engine = await mgr.acquire()
    assert isinstance(engine, CloudEngine)
    assert engine.name == "cloud"
    await mgr.release()
    assert mgr._timer is None  # nothing resident: no idle timer
    # a manual unload still works and is a no-op
    result = await mgr.unload_now()
    assert result["state"] == "unloaded"


@pytest.mark.asyncio
async def test_configure_derives_engine_from_mode():
    mgr = EngineManager(factory=lambda name, model: FakeLocalEngine(name))
    mgr.configure(settings_fn=lambda: {"mode": "cloud"})
    assert mgr.status()["engine"] == "cloud"
    mgr.configure(settings_fn=lambda: {"mode": "local"})
    assert mgr.status()["engine"] == engines.local_engine()
