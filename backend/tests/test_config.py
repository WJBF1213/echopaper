"""Task B1 tests: config defaults, .env loading and env injection."""
import os


def _clear_env(monkeypatch):
    for key in (
        "PORT", "DATA_DIR", "HF_HOME", "HF_ENDPOINT", "PIP_INDEX_URL",
        "ASR_IDLE_UNLOAD_MIN",
        "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
        "LLM_MAX_CONTEXT_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_settings_defaults(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    from app import config

    s = config.load_settings(env_file=tmp_path / "nope.env")
    assert s.port == 8300
    assert s.hf_endpoint == "https://hf-mirror.com"
    assert s.pip_index_url == "https://pypi.tuna.tsinghua.edu.cn/simple"
    assert s.asr.idle_unload_min == 10
    # Engine + model choice is platform-fixed; no AsrSettings fields remain.
    for gone in ("engine", "parakeet_model", "whisper_model", "faster_whisper_model"):
        assert not hasattr(s.asr, gone)
    assert s.llm.provider == "zhipu"
    assert s.llm.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert s.llm.api_key == ""
    # dirs default inside the repo: data/ and .models/
    assert s.data_dir.name == "data"
    assert s.hf_home.name == ".models"


def test_asr_env_keys_reduced_to_idle_unload():
    from app import config

    for gone in (
        "ASR_ENGINE", "ASR_PARAKEET_MODEL", "ASR_WHISPER_MODEL",
        "ASR_FASTER_WHISPER_MODEL", "PARAKEET_MODEL", "WHISPER_MODEL",
        "FASTER_WHISPER_MODEL",
    ):
        assert gone not in config._ENV_KEYS
    assert config._ENV_KEYS["ASR_IDLE_UNLOAD_MIN"] == ("asr.idle_unload_min", int)


def test_legacy_engine_model_env_keys_are_ignored(tmp_path, monkeypatch):
    """A .env written by the old launchers must not crash or change anything."""
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ASR_ENGINE=whisper\n"
        "ASR_WHISPER_MODEL=legacy/whisper\n"
        "FASTER_WHISPER_MODEL=small\n",
        encoding="utf-8",
    )
    from app import config

    s = config.load_settings(env_file=env_file)
    assert s.asr.idle_unload_min == 10
    assert not hasattr(s.asr, "engine")
    assert not hasattr(s.asr, "whisper_model")


def test_load_settings_env_overrides_and_injection(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PORT=8310\n"
        "HF_ENDPOINT=https://test-hf.example.com\n"
        "ASR_IDLE_UNLOAD_MIN=5\n"
        "LLM_API_KEY=secret-key\n",
        encoding="utf-8",
    )
    from app import config

    s = config.load_settings(env_file=env_file)
    assert s.port == 8310
    assert s.hf_endpoint == "https://test-hf.example.com"
    assert s.asr.idle_unload_min == 5
    assert s.llm.api_key == "secret-key"
    # injected into os.environ so lazy engine imports pick them up
    assert os.environ.get("HF_ENDPOINT") == "https://test-hf.example.com"
    assert os.environ.get("HF_HOME")


def test_load_settings_process_env_beats_dotenv(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("ASR_IDLE_UNLOAD_MIN=5\n", encoding="utf-8")
    monkeypatch.setenv("ASR_IDLE_UNLOAD_MIN", "7")
    from app import config

    s = config.load_settings(env_file=env_file)
    assert s.asr.idle_unload_min == 7
