"""Audio file storage helpers (Task B10).

save_upload persists either uploaded bytes or a downloaded URL into
``data_dir/audio/`` and probes duration via ffprobe (None when ffprobe
is missing or the probe fails — never blocks ingestion).
Stdlib + httpx only.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx

DOWNLOAD_TIMEOUT_S = 120.0
ALLOWED_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".webm"}


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
            raise AudioError("缺少音频数据（data/url 二选一）")
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
                    raise AudioError(f"下载失败：HTTP {resp.status_code}")
                with path.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        fh.write(chunk)
    except httpx.HTTPError as exc:
        raise AudioError(f"下载失败：{exc}") from exc


def probe_duration(path: str | Path) -> float | None:
    """ffprobe duration; None when unavailable (never raises)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
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
