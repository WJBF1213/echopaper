"""Audio file storage helpers (Task B10; cloud upload prep in Task 3).

save_upload persists either uploaded bytes or a downloaded URL into
``data_dir/audio/`` and probes duration via ffprobe (None when ffprobe
is missing or the probe fails — never blocks ingestion).

prepare_upload_audio fits an audio file under a cloud provider's upload
size limit (24 MB): oversized files are recompressed to 16 kHz mono
~48 kbps MP3 with PyAV (bundled codecs, no ffmpeg binary needed) and,
when still oversized, split into ~10-minute chunks with their exact
start offsets. Stdlib + httpx + PyAV (lazy) only.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

from app import i18n

DOWNLOAD_TIMEOUT_S = 120.0
ALLOWED_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".webm"}

#: provider upload limit handling (Task 3)
UPLOAD_THRESHOLD_MB = 24.0
CHUNK_SECONDS = 600.0  # ~3.6 MB at 48 kbps — far below any limit
UPLOAD_SAMPLE_RATE = 16000
UPLOAD_BITRATE = 48000


class AudioError(Exception):
    """Download/persist failure."""


def _ext_for(filename: str | None = None, url: str | None = None) -> str:
    for source in (url or "", filename or ""):
        suffix = Path(source.split("?")[0]).suffix.lower()
        if suffix in ALLOWED_EXTS:
            return suffix
    return ".mp3"


def has_supported_ext(filename: str | None) -> bool:
    """True when the name has no extension or a recognised audio extension."""
    suffix = Path(filename or "").suffix.lower()
    return not suffix or suffix in ALLOWED_EXTS


def _copy_stream(src, path: Path) -> None:
    with path.open("wb") as fh:
        shutil.copyfileobj(src, fh, 1 << 20)


def cleanup_incoming(data_dir: Path) -> int:
    """Drop staged uploads orphaned by a restart (no tasks survive it)."""
    incoming = Path(data_dir) / "incoming"
    if not incoming.is_dir():
        return 0
    removed = 0
    for path in incoming.iterdir():
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


async def stage_upload(data_dir: Path, upload) -> Path:
    """Stream a multipart upload into ``data_dir/incoming`` (never RAM).

    The job pipeline adopts the staged file into ``data_dir/audio`` when it
    starts, so a large batch only holds one upload's bytes at a time.
    """
    incoming = Path(data_dir) / "incoming"
    await asyncio.to_thread(incoming.mkdir, parents=True, exist_ok=True)
    ext = _ext_for(getattr(upload, "filename", None))
    path = incoming / f"{uuid.uuid4().hex}{ext}"
    try:
        await upload.seek(0)
        await asyncio.to_thread(_copy_stream, upload.file, path)
    except Exception:
        await asyncio.to_thread(path.unlink, True)
        raise
    return path


async def save_upload(
    data_dir: Path,
    *,
    filename: str | None = None,
    data: bytes | None = None,
    url: str | None = None,
) -> tuple[Path, float | None]:
    """Persist audio (bytes or URL download) -> (path, duration_s|None)."""
    audio_dir = Path(data_dir) / "audio"
    await asyncio.to_thread(audio_dir.mkdir, parents=True, exist_ok=True)
    ext = _ext_for(filename, url)
    path = audio_dir / f"{uuid.uuid4().hex}{ext}"
    try:
        if data is not None:
            await asyncio.to_thread(path.write_bytes, data)
        elif url:
            await _download(url, path)
        else:
            raise AudioError(i18n.t("audio.no_data"))
    except Exception:
        await asyncio.to_thread(path.unlink, True)  # clean partial file
        raise
    duration = await asyncio.to_thread(probe_duration, path)
    return path, duration


async def _download(url: str, path: Path) -> None:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DOWNLOAD_TIMEOUT_S, connect=15.0),
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise AudioError(i18n.t("audio.download_http", status=resp.status_code))
                with path.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        fh.write(chunk)
    except httpx.HTTPError as exc:
        raise AudioError(i18n.t("audio.download_failed", error=exc)) from exc


def probe_duration(path: str | Path) -> float | None:
    """Audio duration in seconds; None when it cannot be determined.

    ffprobe is preferred (accurate for every container). Without it — common
    on a bare Windows install — PyAV (already required by faster-whisper)
    reads the container header, so the UI still shows a duration.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = _ffprobe_duration(ffprobe, path)
        if result is not None:
            return result
    return _av_duration(path)


def _ffprobe_duration(ffprobe: str, path: str | Path) -> float | None:
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _av_duration(path: str | Path) -> float | None:
    try:
        import av

        with av.open(str(path), mode="r") as container:
            if container.duration is not None:
                return float(container.duration / 1_000_000)  # microseconds
            stream = container.streams.audio[0] if container.streams.audio else None
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception:
        return None
    return None


# ------------------------------------------------- cloud upload prep (Task 3)


def _upload_tmp_dir() -> Path:
    tmp = Path(tempfile.gettempdir()) / "echopaper-upload"
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


def _encode_frames(container, stream, frames) -> None:
    for frame in frames:
        for packet in stream.encode(frame):
            container.mux(packet)


def _recompress_mp3(
    src: Path | str,
    dst: Path,
    *,
    sample_rate: int = UPLOAD_SAMPLE_RATE,
    bitrate: int = UPLOAD_BITRATE,
) -> None:
    """Whole-file re-encode to 16 kHz mono MP3 via PyAV."""
    import av

    resampler = av.AudioResampler(
        format="s16", layout="mono", rate=sample_rate
    )
    in_c = av.open(str(src))
    out_c = av.open(str(dst), "w")
    try:
        out_s = out_c.add_stream("mp3", rate=sample_rate)
        out_s.layout = "mono"
        out_s.bit_rate = bitrate
        for frame in in_c.decode(audio=0):
            _encode_frames(out_c, out_s, resampler.resample(frame))
        for packet in out_s.encode(None):  # flush the encoder
            out_c.mux(packet)
    finally:
        in_c.close()
        out_c.close()


def _split_mp3(
    src: Path,
    tmp_dir: Path,
    chunk_seconds: float,
    *,
    sample_rate: int = UPLOAD_SAMPLE_RATE,
    bitrate: int = UPLOAD_BITRATE,
) -> list[tuple[str, float]]:
    """Re-encode ``src`` (already 16 kHz mono MP3) into consecutive
    ``chunk_seconds`` windows. Cuts land on exact sample counts, so each
    offset is exactly ``index * chunk_seconds``."""
    import av

    window = int(chunk_seconds * sample_rate)
    resampler = av.AudioResampler(
        format="s16", layout="mono", rate=sample_rate
    )
    in_c = av.open(str(src))
    outputs: list[tuple[Any, Any, Path, float]] = []
    samples = 0
    try:
        for frame in in_c.decode(audio=0):
            for resampled in resampler.resample(frame):
                index = samples // window  # window the frame STARTS in
                while len(outputs) <= index:
                    path = tmp_dir / f"upload-{uuid.uuid4().hex}-{len(outputs)}.mp3"
                    container = av.open(str(path), "w")
                    stream = container.add_stream("mp3", rate=sample_rate)
                    stream.layout = "mono"
                    stream.bit_rate = bitrate
                    outputs.append(
                        (container, stream, path, len(outputs) * chunk_seconds)
                    )
                samples += resampled.samples
                _encode_frames(outputs[index][0], outputs[index][1], [resampled])
    finally:
        for container, stream, _path, _off in outputs:
            for packet in stream.encode(None):
                container.mux(packet)
            container.close()
        in_c.close()
    return [(str(path), offset) for _c, _s, path, offset in outputs]


def prepare_upload_audio(
    path: str | Path,
    *,
    threshold_mb: float = UPLOAD_THRESHOLD_MB,
    chunk_seconds: float = CHUNK_SECONDS,
) -> list[tuple[str, float]]:
    """Fit audio under a provider upload limit (Task 3).

    Returns ``[(file_path, offset_seconds)]`` for sequential upload:
    ``[(original, 0.0)]`` when the file already fits; otherwise one
    recompressed 16 kHz mono ~48 kbps MP3 (offset 0); if even that
    exceeds the limit, ~``chunk_seconds`` chunks whose word times must
    be offset by the chunk start. Files other than the original are
    temporary — the CALLER deletes them after transcription.
    """
    src = Path(path)
    limit = threshold_mb * 1024 * 1024
    if src.stat().st_size <= limit:
        return [(str(src), 0.0)]
    tmp_dir = _upload_tmp_dir()
    whole = tmp_dir / f"upload-{uuid.uuid4().hex}.mp3"
    _recompress_mp3(src, whole)
    if whole.stat().st_size <= limit:
        return [(str(whole), 0.0)]
    chunks = _split_mp3(whole, tmp_dir, chunk_seconds)
    whole.unlink(missing_ok=True)
    return chunks
