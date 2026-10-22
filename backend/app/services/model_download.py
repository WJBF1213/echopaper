"""Model resolution for faster-whisper with a China-friendly fallback.

faster-whisper resolves model names through Hugging Face. In mainland China
``huggingface.co`` is often unreachable and ``hf-mirror.com`` can time out, so
a fresh install would fail at first transcription with a network error that
says nothing about the fix.

Resolution order for a name like ``large-v3-turbo``:
1. A local directory that already contains ``model.bin`` (offline / air-gapped).
2. A bundle previously downloaded by this module into
   ``$HF_HOME/faster-whisper/<name>``.
3. The Hugging Face name itself (faster-whisper handles the download).

``ensure_model`` tries the fast path first (a HEAD request with a short
timeout) and only falls back to ModelScope when HF is unreachable. ModelScope
mirrors the same CTranslate2 files, so the bytes are identical in shape and
the resulting model behaves the same.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx

# ModelScope namespaces that mirror the common faster-whisper conversions.
MODELSCOPE_REPOS = {
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "mobiuslabsgmbh/faster-whisper-large-v3",
    "medium": "mobiuslabsgmbh/faster-whisper-medium",
    "small": "mobiuslabsgmbh/faster-whisper-small",
    "base": "mobiuslabsgmbh/faster-whisper-base",
    "tiny": "mobiuslabsgmbh/faster-whisper-tiny",
}

MODELSCOPE_BASE = "https://modelscope.cn/models/{repo}/resolve/master"
REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.json")

HF_PROBE_TIMEOUT_S = 6.0
DOWNLOAD_TIMEOUT_S = httpx.Timeout(30.0, read=120.0)


class ModelDownloadError(Exception):
    """The model could not be resolved locally, from HF, or from ModelScope."""


def cache_dir() -> Path:
    """Where ModelScope bundles land (inside the configured HF cache)."""
    root = os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface")
    return Path(root) / "faster-whisper"


def _is_complete(path: Path) -> bool:
    return all((path / name).is_file() for name in REQUIRED_FILES)


def is_local_model(name: str) -> bool:
    return Path(name).is_dir() and _is_complete(Path(name))


def _hf_reachable() -> bool:
    """Cheap probe so a dead HF endpoint costs seconds, not a hung download."""
    endpoint = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    try:
        httpx.head(endpoint, timeout=HF_PROBE_TIMEOUT_S, follow_redirects=True)
        return True
    except Exception:
        return False


def _download_from_modelscope(name: str, dest: Path) -> Path:
    repo = MODELSCOPE_REPOS.get(name)
    if repo is None:
        raise ModelDownloadError(
            f"HF 不可达，且模型 {name} 没有 ModelScope 镜像；"
            "请手动下载 CTranslate2 模型目录，并把设置页的模型名填成该目录的绝对路径"
        )
    dest.mkdir(parents=True, exist_ok=True)
    base = MODELSCOPE_BASE.format(repo=repo)
    for filename in REQUIRED_FILES + ("preprocessor_config.json",):
        path = dest / filename
        if path.is_file() and path.stat().st_size > 0:
            continue
        partial = path.with_suffix(path.suffix + ".part")
        try:
            with httpx.stream(
                "GET", f"{base}/{filename}", timeout=DOWNLOAD_TIMEOUT_S,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
            partial.replace(path)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise ModelDownloadError(
                f"从 ModelScope 下载 {filename} 失败：{exc}"
            ) from exc
    if not _is_complete(dest):
        raise ModelDownloadError(f"ModelScope 下载不完整：{dest}")
    return dest


def ensure_model(name: str) -> str:
    """Return a value safe to pass to ``WhisperModel``.

    Local paths and HF-hosted names pass through; a model we already mirrored
    resolves to its cache directory; HF-unreachable environments are served
    from ModelScope.
    """
    if is_local_model(name):
        return name

    cached = cache_dir() / name
    if _is_complete(cached):
        return str(cached)

    if name not in MODELSCOPE_REPOS:
        # Unknown model: hand it to faster-whisper unchanged and let its own
        # error surface; nothing better we can do.
        return name

    if _hf_reachable():
        return name  # faster-whisper downloads it from HF as usual

    return str(_download_from_modelscope(name, cached))


def clear_cache(name: str) -> bool:
    """Remove a mirrored bundle (used by tests and manual cleanup)."""
    target = cache_dir() / name
    if target.is_dir():
        shutil.rmtree(target)
        return True
    return False
