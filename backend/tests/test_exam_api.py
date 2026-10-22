"""API tests for the question-type registry endpoint (six-key redesign)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class _FakeEngineManager:
    def configure(self, **kw):
        pass

    async def switch(self, name):
        return {"ok": True}

    async def load(self):
        return {"ok": True}

    async def unload(self):
        return {"unloaded": True}

    def status(self):
        return {"engine": "faster_whisper", "detail": None}


@pytest.fixture
def client(tmp_db, tmp_path):
    app = create_app(
        conn=tmp_db,
        data_dir=tmp_path,
        dist_dir=tmp_path / "missing_dist",
        engine_manager=_FakeEngineManager(),
    )
    return TestClient(app)


def test_exam_types_lists_six_key_registry(client):
    res = client.get("/api/exam/types")
    assert res.status_code == 200
    data = res.json()

    types = {t["key"]: t for t in data["types"]}
    assert set(types) == {
        "mcq_single", "mcq_multi", "matching",
        "completion", "short_answer", "map_labelling",
    }
    # Part is no longer an input and part presets are gone (design §4.2).
    assert all("parts" not in t for t in data["types"])
    assert "presets" not in data

    # The six legacy fill-in types survive only as completion's layouts.
    assert types["completion"]["layouts"] == [
        "form", "table", "notes", "sentence", "summary", "flowchart",
    ]
    assert types["completion"]["answer_kind"] == "span"

    # map_labelling generates a scene asset (design §4.3).
    assert types["map_labelling"]["generates_visual"] is True
    assert types["map_labelling"]["answer_kind"] == "matching"

    assert types["mcq_single"]["answer_kind"] == "option"
    assert types["mcq_multi"]["answer_kind"] == "option_multi"
    assert types["matching"]["answer_kind"] == "matching"
    assert types["short_answer"]["answer_kind"] == "span"

    # max_count cap and the deterministic precheck floor (design §4.5).
    assert all(t["max_count"] == 10 for t in data["types"])
    assert types["mcq_single"]["min_words"] == 120
    assert types["mcq_multi"]["min_words"] == 200
    assert types["matching"]["min_words"] == 150
    assert types["completion"]["min_words"] == 80
    assert types["short_answer"]["min_words"] == 80
    assert types["map_labelling"]["min_words"] == 200

    # Names ship in both languages; "name" follows the request locale.
    assert types["completion"]["name_zh"] == "填空题"
    assert types["completion"]["name_en"] == "Completion"
    assert types["completion"]["name"] == "填空题"  # default locale is zh


# ----------------------------------------------- T10: restored on blocks API
# The POST /api/materials/{id}/exam tests (part/preset contract) were
# temporarily removed with the preset registry in Task 9 (PRESETS /
# PaperPreset / parts deleted, design §4.2). Task 10 reintroduces
# generation as the blocks API ({blocks: [{type, count}]}) and restores /
# rewrites:
#   - request validation (unknown type, count over max_count, word floor)
#   - LLM-key requirement
#   - stub-LLM paper generation + refusal (skipped) handling
