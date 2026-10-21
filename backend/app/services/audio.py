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


async def save_upload(
    data_dir: Path,
    *,
    filename: str | None = None,
    data: bytes | None = None,
    url: str | None = None,
) -> tuple[Path, float | None]:
    """Persist audio (bytes or URL download) -> (path, duration_s|None)."""
    audio_dir = Path(data_dir) / "audio"
    await asyncio.to_thread(audio_dir.mkdir, True, True)
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
