"""Cloud ASR settings API tests (Task 3).

- GET /api/settings masks ``cloud_api_key`` exactly like ``llm.api_key``
- PUT with empty-string ``cloud_api_key`` keeps the stored one
- PUT ``mode``: cloud <-> local switches the engine manager (409 when
  busy, nothing persisted), invalid mode -> localized 400
- POST /api/asr/test-cloud: form overrides, blank key -> stored key,
  no key -> ok=false (llm.no_key pattern)
- config: cloud env keys + defaults

All requests run against the real app with fake managers; no network.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import engines as engines_mod


class FakeEngineManager:
    def __init__(self):
        self.calls = []
        self.busy = False

    def configure(self, **kw):
        pass

    async def acquire(self):
        return self

    async def release(self):
        pass

    async def unload_now(self):
        return {"state": "unloaded", "engine": "parakeet", "model": "m",
                "idle_unload_min": 10}

    async def switch(self, name):
        self.calls.append(name)
        if self.busy:
            return {"state": "ready", "engine": "parakeet", "busy": True,
                    "detail": "busy: transcription in progress"}
        return {"state": "unloaded", "engine": name, "model": "",
                "idle_unload_min": 10}

    def status(self):
        return {"state": "unloaded", "engine": "parakeet", "model": "m",
                "idle_unload_min": 10}


class FakeJobs:
    def __init__(self):
        self.payload = None

    def configure(self, **kw):
        pass

    async def create(self, payload, **kw):
        self.payload = payload
        return "job-1"

    def get(self, job_id):
        return {"id": job_id, "state": "done", "percent": 100.0}


@pytest.fixture()
def manager():
    return FakeEngineManager()


@pytest.fixture()
def app(tmp_db, tmp_path, manager):
    application = create_app(
        conn=tmp_db,
        data_dir=tmp_path,
        dist_dir=tmp_path / "missing_dist",
        engine_manager=manager,
        jobs_manager=FakeJobs(),
    )
    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


# ---------------- GET shape + masking ----------------


def test_get_settings_default_cloud_shape(client):
    asr = client.get("/api/settings").json()["asr"]
    assert asr == {
        "mode": "local",
        "engine": engines_mod.local_engine(),
        "idle_unload_min": 10,
        "cloud_base_url": "https://api.groq.com/openai/v1",
        "cloud_model": "whisper-large-v3-turbo",
        "has_cloud_key": False,
        "cloud_key_masked": None,
    }


def test_get_settings_masks_cloud_key(tmp_db, client):
    r = client.put("/api/settings", json={
        "asr": {"cloud_api_key": "sk-cloud-secret-123456"}
    })
    assert r.status_code == 200
    body = client.get("/api/settings").json()
    asr = body["asr"]
    assert "cloud_api_key" not in asr
    assert "sk-cloud-secret-123456" not in str(body)
    assert asr["has_cloud_key"] is True
    assert asr["cloud_key_masked"] == "sk-c****3456"
    # the real value lives only in the DB row
    from app import db as db_mod
    stored = db_mod.get_setting(tmp_db, "asr")
    assert stored["cloud_api_key"] == "sk-cloud-secret-123456"


def test_put_empty_cloud_key_keeps_stored(tmp_db, client):
    from app import db as db_mod

    client.put("/api/settings", json={
        "asr": {"cloud_api_key": "sk-first-1234"}
    })
    r = client.put("/api/settings", json={
        "asr": {"cloud_api_key": "", "cloud_model": "other-model"}
    })
    assert r.status_code == 200
    stored = db_mod.get_setting(tmp_db, "asr")
    assert stored["cloud_api_key"] == "sk-first-1234"
    assert stored["cloud_model"] == "other-model"
    assert client.get("/api/settings").json()["asr"]["has_cloud_key"] is True


# ---------------- mode switching ----------------


def test_put_mode_cloud_switches_engine(client, manager):
    r = client.put("/api/settings", json={"asr": {"mode": "cloud"}})
    assert r.status_code == 200
    assert manager.calls == ["cloud"]
    asr = client.get("/api/settings").json()["asr"]
    assert asr["mode"] == "cloud"
    assert asr["engine"] == "cloud"


def test_put_mode_local_switches_back(client, manager):
    client.put("/api/settings", json={"asr": {"mode": "cloud"}})
    r = client.put("/api/settings", json={"asr": {"mode": "local"}})
    assert r.status_code == 200
    assert manager.calls == ["cloud", engines_mod.local_engine()]
    asr = client.get("/api/settings").json()["asr"]
    assert asr["mode"] == "local"
    assert asr["engine"] == engines_mod.local_engine()


def test_put_same_mode_does_not_reswitch(client, manager):
    client.put("/api/settings", json={"asr": {"mode": "cloud"}})
    r = client.put("/api/settings", json={
        "asr": {"mode": "cloud", "cloud_model": "m2"}
    })
    assert r.status_code == 200
    assert manager.calls == ["cloud"]  # no second switch
    # non-mode patches never touch the engine
    client.put("/api/settings", json={"asr": {"idle_unload_min": 3}})
    assert manager.calls == ["cloud"]


def test_put_invalid_mode_is_400_localized(client, manager, tmp_db):
    from app import db as db_mod

    r = client.put("/api/settings", json={"asr": {"mode": "bogus"}})
    assert r.status_code == 400
    assert "bogus" in r.json()["detail"]
    assert manager.calls == []
    stored = db_mod.get_setting(tmp_db, "asr")
    assert stored is None or "mode" not in (stored or {})
    assert client.get("/api/settings").json()["asr"]["mode"] == "local"


def test_put_mode_busy_returns_409_and_keeps_mode(client, manager, tmp_db):
    from app import db as db_mod

    manager.busy = True
    r = client.put("/api/settings", json={"asr": {"mode": "cloud"}})
    assert r.status_code == 409
    assert manager.calls == ["cloud"]
    stored = db_mod.get_setting(tmp_db, "asr")
    assert stored is None or "mode" not in (stored or {})
    assert client.get("/api/settings").json()["asr"]["engine"] != "cloud"


def test_legacy_asr_row_still_cleaned_by_put(client, tmp_db):
    from app import db as db_mod

    db_mod.set_setting(tmp_db, "asr", {
        "engine": "whisper", "whisper_model": "x", "idle_unload_min": 3,
    })
    client.put("/api/settings", json={"asr": {"mode": "local"}})
    stored = db_mod.get_setting(tmp_db, "asr")
    # legacy junk dropped; valid stored subkeys carry over
    assert stored == {"mode": "local", "idle_unload_min": 3}


# ---------------- POST /api/asr/test-cloud ----------------


def test_test_cloud_passes_form_overrides(client, monkeypatch):
    from app.services import cloud_engine

    captured = {}

    async def fake(cfg):
        captured.update(cfg)
        return True, "连接正常"

    monkeypatch.setattr(cloud_engine, "test_cloud_connection", fake)
    r = client.post("/api/asr/test-cloud", json={
        "cloud_base_url": "https://fake.example/v1",
        "cloud_model": "my-model",
        "cloud_api_key": "sk-typed-not-saved",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "连接正常"}
    assert captured["cloud_api_key"] == "sk-typed-not-saved"
    assert captured["cloud_base_url"] == "https://fake.example/v1"
    assert captured["cloud_model"] == "my-model"


def test_test_cloud_blank_key_uses_stored(client, monkeypatch):
    from app.services import cloud_engine

    client.put("/api/settings", json={
        "asr": {"cloud_api_key": "sk-stored-cloud"}
    })
    captured = {}

    async def fake(cfg):
        captured.update(cfg)
        return True, "ok"

    monkeypatch.setattr(cloud_engine, "test_cloud_connection", fake)
    r = client.post("/api/asr/test-cloud", json={"cloud_api_key": ""})
    assert r.json()["ok"] is True
    assert captured["cloud_api_key"] == "sk-stored-cloud"


def test_test_cloud_without_any_key(client, monkeypatch):
    from app.config import Settings
    from app.routers import settings as settings_router
    from app.services import cloud_engine

    monkeypatch.setattr(settings_router, "load_settings",
                        lambda: Settings())

    async def unreachable(cfg):
        raise AssertionError("probe must not run without a key")

    monkeypatch.setattr(cloud_engine, "test_cloud_connection", unreachable)
    r = client.post("/api/asr/test-cloud", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "API key" in body["message"]


# ---------------- config: env keys + defaults ----------------


def test_asr_settings_cloud_defaults():
    from app.config import AsrSettings

    s = AsrSettings()
    assert s.mode == "local"
    assert s.idle_unload_min == 10
    assert s.cloud_base_url == "https://api.groq.com/openai/v1"
    assert s.cloud_model == "whisper-large-v3-turbo"
    assert s.cloud_api_key == ""


def test_cloud_env_keys_mapped(tmp_path, monkeypatch):
    from app import config

    for key in ("ASR_MODE", "ASR_CLOUD_BASE_URL", "ASR_CLOUD_MODEL",
                "ASR_CLOUD_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert config._ENV_KEYS["ASR_MODE"] == ("asr.mode", str)
    assert config._ENV_KEYS["ASR_CLOUD_BASE_URL"] == ("asr.cloud_base_url", str)
    assert config._ENV_KEYS["ASR_CLOUD_MODEL"] == ("asr.cloud_model", str)
    assert config._ENV_KEYS["ASR_CLOUD_API_KEY"] == ("asr.cloud_api_key", str)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "ASR_MODE=cloud\n"
        "ASR_CLOUD_BASE_URL=https://fake.example/v1\n"
        "ASR_CLOUD_MODEL=my-model\n"
        "ASR_CLOUD_API_KEY=sk-from-env\n",
        encoding="utf-8",
    )
    s = config.load_settings(env_file=env_file)
    assert s.asr.mode == "cloud"
    assert s.asr.cloud_base_url == "https://fake.example/v1"
    assert s.asr.cloud_model == "my-model"
    assert s.asr.cloud_api_key == "sk-from-env"
