"""Task 6 API tests: GET/PUT /api/prompts (registry + overrides)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import prompts


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


class _FakeJobs:
    def configure(self, **kw):
        pass


@pytest.fixture
def client(tmp_db, tmp_path):
    app = create_app(
        conn=tmp_db,
        data_dir=tmp_path,
        dist_dir=tmp_path / "missing_dist",
        engine_manager=_FakeEngineManager(),
        jobs_manager=_FakeJobs(),
    )
    return TestClient(app)


def test_list_prompts(client):
    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    entries = resp.json()
    # T9: the registry is data-driven; its size follows ALL_PROMPTS
    # (18 after the six-key swap) instead of a hardcoded count.
    assert len(entries) == len(prompts.ALL_PROMPTS)

    fields = {"key", "title", "category", "variables", "default", "current",
              "customized"}
    for entry in entries:
        assert fields <= set(entry)

    by_key = {e["key"]: e for e in entries}
    assert by_key["exam.system.zh"]["customized"] is False
    assert by_key["exam.system.zh"]["current"] == by_key["exam.system.zh"]["default"]
    assert by_key["exam.task_frame.zh"]["variables"] == [
        "part", "label", "count", "instruction", "rules", "gap", "schema"]

    # title follows Accept-Language (default zh without the header).
    assert by_key["exam.system.zh"]["title"] == "系统提示 · 中文"
    en = {
        e["key"]: e
        for e in client.get(
            "/api/prompts", headers={"Accept-Language": "en-US,en;q=0.9"}
        ).json()
    }
    assert en["exam.system.zh"]["title"] == "System prompt · Chinese"
    assert en["exam.rules.completion.en"]["title"] == "Rules · Completion"


def test_put_override_and_reset(client):
    key = "exam.system.zh"
    default = prompts.get_prompt(
        client.app.state.conn, key
    )

    # 1. PUT a custom text -> customized, current updated, default intact.
    resp = client.put("/api/prompts", json={"key": key, "text": "你是测试命题人。"})
    assert resp.status_code == 200
    assert resp.json()["customized"] is True
    assert resp.json()["current"] == "你是测试命题人。"

    listed = {
        e["key"]: e for e in client.get("/api/prompts").json()
    }
    assert listed[key]["customized"] is True
    assert listed[key]["current"] == "你是测试命题人。"
    assert listed[key]["default"] == default

    # 2. PUT an empty string -> RESET to default.
    resp = client.put("/api/prompts", json={"key": key, "text": ""})
    assert resp.status_code == 200
    assert resp.json()["customized"] is False
    assert resp.json()["current"] == default

    # 3. PUT null text also resets (same semantic as empty string).
    client.put("/api/prompts", json={"key": key, "text": "再次自定义。"})
    resp = client.put("/api/prompts", json={"key": key, "text": None})
    assert resp.status_code == 200
    assert resp.json()["customized"] is False
    assert resp.json()["current"] == default


def test_put_missing_placeholder_400(client):
    key = "exam.stable_frame.zh"  # declares {{transcript}} + {{candidates}}

    # Missing every placeholder -> 400 naming both.
    resp = client.put(
        "/api/prompts", json={"key": key, "text": "完全没有占位符的文本"}
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "{{transcript}}" in detail
    assert "{{candidates}}" in detail

    # Missing only one -> 400 naming just that one; nothing is saved.
    resp = client.put(
        "/api/prompts",
        json={"key": key, "text": "转写：{{transcript}}（缺少候选）"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "{{candidates}}" in detail
    assert "{{transcript}}" not in detail

    listed = {
        e["key"]: e for e in client.get("/api/prompts").json()
    }
    assert listed[key]["customized"] is False
    assert listed[key]["current"] == listed[key]["default"]

    # A text carrying every declared placeholder is accepted.
    ok = client.put(
        "/api/prompts",
        json={"key": key, "text": "T: {{transcript}}\nC: {{candidates}}"},
    )
    assert ok.status_code == 200
    assert ok.json()["customized"] is True


def test_put_unknown_key_404(client):
    resp = client.put(
        "/api/prompts", json={"key": "exam.nope.zh", "text": "随便什么"}
    )
    assert resp.status_code == 404


def test_delete_llm_cache(client):
    """Task 8: DELETE /api/llm-cache wipes the response cache and reports
    how many rows went away; a second call on an empty table reports 0."""
    conn = client.app.state.conn
    for i in range(2):
        conn.execute(
            "INSERT INTO llm_cache(cache_key, task, model, response_json,"
            " prompt_tokens, completion_tokens, cached_tokens, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (f"key-{i}", "exam", "glm-4.7-flash", "{}", 1, 2, 0, "2026-01-01"),
        )
    conn.commit()

    resp = client.delete("/api/llm-cache")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}

    # The table is now empty — deleting again removes nothing.
    resp = client.delete("/api/llm-cache")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0}
    assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
