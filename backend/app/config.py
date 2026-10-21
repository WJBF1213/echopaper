"""Application settings loaded from environment / .env (Task B1).

``load_settings()`` must be called before any ASR engine module is imported:
it injects ``HF_HOME`` / ``HF_ENDPOINT`` into ``os.environ`` so the lazy
huggingface_hub downloads go to the project cache via the CN mirror.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_ENV_KEYS = {
    "PORT": ("port", int),
    "DATA_DIR": ("data_dir", str),
    "HF_HOME": ("hf_home", str),
    "HF_ENDPOINT": ("hf_endpoint", str),
    "PIP_INDEX_URL": ("pip_index_url", str),
    "ASR_ENGINE": ("asr.engine", str),
    "PARAKEET_MODEL": ("asr.parakeet_model", str),
    "WHISPER_MODEL": ("asr.whisper_model", str),
    "ASR_IDLE_UNLOAD_MIN": ("asr.idle_unload_min", int),
    "LLM_PROVIDER": ("llm.provider", str),
    "LLM_BASE_URL": ("llm.base_url", str),
    "LLM_MODEL": ("llm.model", str),
    "LLM_API_KEY": ("llm.api_key", str),
    "GEN_BLANK_COUNT": ("gen.blank_count", int),
}


@dataclass
class AsrSettings:
    engine: str = "parakeet"  # 'parakeet' | 'whisper'
    parakeet_model: str = "mlx-community/parakeet-tdt-0.6b-v3"
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    idle_unload_min: int = 10  # 0 disables idle unload


@dataclass
class LlmSettings:
    provider: str = "zhipu"
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4.7-flash"
    api_key: str = ""


@dataclass
class GenSettings:
    blank_count: int = 10


@dataclass
class Settings:
    port: int = 8300
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    hf_home: Path = field(default_factory=lambda: REPO_ROOT / ".models")
    hf_endpoint: str = "https://hf-mirror.com"
    pip_index_url: str = "https://pypi.tuna.tsinghua.edu.cn/simple"
    asr: AsrSettings = field(default_factory=AsrSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    gen: GenSettings = field(default_factory=GenSettings)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _apply(target: Settings, dotted: str, value: str) -> None:
    parts = dotted.split(".")
    obj: object = target
    for p in parts[:-1]:
        obj = getattr(obj, p)
    current = getattr(obj, parts[-1])
    if isinstance(current, bool):
        converted: object = value.lower() in ("1", "true", "yes", "on")
    elif isinstance(current, int):
        converted = int(value)
    elif isinstance(current, Path):
        converted = Path(value)
    else:
        converted = value
    setattr(obj, parts[-1], converted)


def load_settings(env_file: Path | None = None) -> Settings:
    """Build Settings from process env overlaid on an optional .env file.

    Process environment takes precedence over .env values. Side effect:
    ``HF_HOME`` / ``HF_ENDPOINT`` / ``PIP_INDEX_URL`` are injected into
    ``os.environ`` (if not already set) so lazily imported engine code and
    pip subprocesses see them.
    """
    settings = Settings()
    dotenv = _parse_env_file(env_file if env_file is not None else REPO_ROOT / ".env")
    for env_key, (dotted, _cast) in _ENV_KEYS.items():
        value = os.environ.get(env_key) or dotenv.get(env_key)
        if value is not None and value != "":
            _apply(settings, dotted, value)

    os.environ.setdefault("HF_HOME", str(settings.hf_home))
    os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
    os.environ.setdefault("PIP_INDEX_URL", settings.pip_index_url)
    os.environ["HF_ENDPOINT"] = settings.hf_endpoint
    os.environ["HF_HOME"] = str(settings.hf_home)
    return settings
