"""Model resolution tests: local dir → cache → HF → ModelScope fallback."""
from pathlib import Path

import pytest

from app.services import model_download as md


def _make_bundle(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in md.REQUIRED_FILES:
        (path / name).write_bytes(b"x")
    return path


@pytest.fixture(autouse=True)
def isolated_hf_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    return tmp_path


def test_local_directory_is_used_as_is(tmp_path):
    bundle = _make_bundle(tmp_path / "my-model")
    assert md.is_local_model(str(bundle)) is True
    assert md.ensure_model(str(bundle)) == str(bundle)


def test_incomplete_local_directory_is_not_trusted(tmp_path, monkeypatch):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "config.json").write_bytes(b"x")
    monkeypatch.setattr(md, "_hf_reachable", lambda: True)
    assert md.is_local_model(str(broken)) is False
    # Unknown names are handed to faster-whisper unchanged.
    assert md.ensure_model(str(broken)) == str(broken)


def test_cached_bundle_short_circuits_network(tmp_path, monkeypatch):
    cached = _make_bundle(md.cache_dir() / "large-v3-turbo")

    def boom():
        raise AssertionError("network must not be probed when the bundle is cached")

    monkeypatch.setattr(md, "_hf_reachable", boom)
    assert md.ensure_model("large-v3-turbo") == str(cached)


def test_hf_reachable_keeps_the_model_name(monkeypatch):
    monkeypatch.setattr(md, "_hf_reachable", lambda: True)
    assert md.ensure_model("large-v3-turbo") == "large-v3-turbo"


def test_hf_unreachable_uses_modelscope(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "_hf_reachable", lambda: False)
    calls = []

    def fake_download(name, dest):
        calls.append((name, dest))
        return _make_bundle(dest)

    monkeypatch.setattr(md, "_download_from_modelscope", fake_download)
    resolved = md.ensure_model("large-v3-turbo")
    assert calls and calls[0][0] == "large-v3-turbo"
    assert Path(resolved).is_dir()
    assert md.is_local_model(resolved)


def test_unknown_model_without_mirror_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(md, "_hf_reachable", lambda: False)
    assert md.ensure_model("distil-whisper-custom") == "distil-whisper-custom"


def test_unknown_model_raises_only_when_downloading(monkeypatch):
    monkeypatch.setattr(md, "_hf_reachable", lambda: False)
    with pytest.raises(md.ModelDownloadError):
        md._download_from_modelscope("distil-whisper-custom", md.cache_dir() / "x")


def test_model_mapping_has_the_default_model():
    assert "large-v3-turbo" in md.MODELSCOPE_REPOS
