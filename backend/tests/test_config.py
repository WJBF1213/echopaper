"""Task B1 tests: config defaults, .env loading and env injection."""
import os


def _clear_env(monkeypatch):
    for key in (
        "PORT", "DATA_DIR", "HF_HOME", "HF_ENDPOINT", "PIP_INDEX_URL",
        "ASR_ENGINE", "PARAKEET_MODEL", "WHISPER_MODEL", "ASR_IDLE_UNLOAD_MIN",
        "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
        "GEN_BLANK_COUNT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_settings_defaults(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    from app import config

    s = config.load_settings(env_file=tmp_path / "nope.env")
    assert s.port == 8300
    assert s.hf_endpoint == "https://hf-mirror.com"
    assert s.pip_index_url == "https://pypi.tuna.tsinghua.edu.cn/simple"
    assert s.asr.engine == "parakeet"
    assert s.asr.parakeet_model == "mlx-community/parakeet-tdt-0.6b-v3"
    assert s.asr.whisper_model == "mlx-community/whisper-large-v3-turbo"
    assert s.asr.idle_unload_min == 10
    assert s.llm.provider == "zhipu"
    assert s.llm.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert s.llm.api_key == ""
    assert s.gen.blank_count == 10
    # dirs default inside the repo: data/ and .models/
    assert s.data_dir.name == "data"
    assert s.hf_home.name == ".models"


def test_load_settings_env_overrides_and_injection(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PORT=8310\n"
        "HF_ENDPOINT=https://test-hf.example.com\n"
        "ASR_ENGINE=whisper\n"
        "LLM_API_KEY=secret-key\n"
        "GEN_BLANK_COUNT=20\n",
        encoding="utf-8",
    )
    from app import config

    s = config.load_settings(env_file=env_file)
    assert s.port == 8310
    assert s.hf_endpoint == "https://test-hf.example.com"
    assert s.asr.engine == "whisper"
    assert s.llm.api_key == "secret-key"
    assert s.gen.blank_count == 20
    # injected into os.environ so lazy engine imports pick them up
    assert os.environ.get("HF_ENDPOINT") == "https://test-hf.example.com"
    assert os.environ.get("HF_HOME")


def test_load_settings_process_env_beats_dotenv(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("ASR_ENGINE=whisper\n", encoding="utf-8")
    monkeypatch.setenv("ASR_ENGINE", "parakeet")
    from app import config

    s = config.load_settings(env_file=env_file)
    assert s.asr.engine == "parakeet"
