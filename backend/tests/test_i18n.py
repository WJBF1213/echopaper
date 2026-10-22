"""i18n catalog integrity + Accept-Language middleware tests."""
import pytest
from fastapi.testclient import TestClient

from app import i18n
from app.main import create_app


class _FakeEngineManager:
    def configure(self, **kw):
        pass


class _FakeJobs:
    def configure(self, **kw):
        pass


@pytest.fixture()
def client(tmp_db, tmp_path):
    """Same app wiring as test_api.py: real DB + fake managers."""
    application = create_app(
        conn=tmp_db,
        data_dir=tmp_path,
        dist_dir=tmp_path / "missing_dist",
        engine_manager=_FakeEngineManager(),
        jobs_manager=_FakeJobs(),
    )
    return TestClient(application)


def test_catalogs_share_keys_and_are_non_empty():
    assert set(i18n.MESSAGES) == set(i18n.SUPPORTED)
    keys = set(i18n.MESSAGES["zh"])
    assert len(keys) >= 59
    for locale in i18n.SUPPORTED:
        assert set(i18n.MESSAGES[locale]) == keys, locale
        empty = [k for k, v in i18n.MESSAGES[locale].items() if not v.strip()]
        assert empty == [], (locale, empty)


@pytest.mark.parametrize(
    "header, expected",
    [
        ("en-US,en;q=0.9", "en"),
        ("zh-CN", "zh"),
        ("EN-gb", "en"),
        ("fr-FR,fr;q=0.9", "zh"),  # unknown -> default
        ("de", "zh"),
        ("fr-FR,en;q=0.9", "en"),  # first supported tag wins
        ("", "zh"),
        (None, "zh"),
    ],
)
def test_normalize_locale(header, expected):
    assert i18n.normalize_locale(header) == expected


def test_t_interpolation_and_unknown_key():
    token = i18n.set_locale("en")
    try:
        assert i18n.t("common.unknown_mode", mode="llm") == "Unknown mode: llm"
        assert i18n.t("no.such.key") == "no.such.key"
        # Missing params leave the template intact instead of raising.
        assert "{mode}" in i18n.t("common.unknown_mode")
    finally:
        i18n.reset_locale(token)

    assert i18n.get_locale() == i18n.DEFAULT_LOCALE
    assert i18n.t("common.unknown_mode", mode="nouns") == "未知模式：nouns"
    assert i18n.t("no.such.key") == "no.such.key"


def test_set_locale_rejects_unsupported():
    token = i18n.set_locale("fr")
    try:
        assert i18n.get_locale() == i18n.DEFAULT_LOCALE
    finally:
        i18n.reset_locale(token)


def test_accept_language_middleware_localizes_404_detail(client):
    en = client.get(
        "/api/materials/missing", headers={"Accept-Language": "en-US,en;q=0.9"}
    )
    assert en.status_code == 404
    assert en.json()["detail"] == "Material not found"

    zh = client.get(
        "/api/materials/missing", headers={"Accept-Language": "zh-CN"}
    )
    assert zh.status_code == 404
    assert zh.json()["detail"] == "材料不存在"

    # No header -> default Chinese; the previous request's locale did not leak.
    default = client.get("/api/materials/missing")
    assert default.status_code == 404
    assert default.json()["detail"] == "材料不存在"
