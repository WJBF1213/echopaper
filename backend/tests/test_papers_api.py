"""Papers persistence + CRUD API tests (design §5.1/§5.2, Task 14).

``POST /api/materials/{id}/exam`` persists one ``papers`` row per
generation (spec/paper/generation JSON, stale=0) and answers
``{paper_id, paper, skipped}``; ``GET /materials/{id}/papers`` lists
summaries newest first, ``GET/DELETE /papers/{id}`` fetch and remove.
Editing the transcript marks every paper of the material stale=1 (still
fetchable). ``regenerate`` now derives its variation marker from the
REAL persisted paper count (the deferred T10 covering test). Map items
carry an explicit ``slot`` field end to end (T13 review rider).
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import ChatUsage

from test_exam_gen import (  # noqa: E402  (same-directory test module)
    MAP_TALK,
    find_span,
    make_material,
    make_scene,
)


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


_SEED_TEXTS = [
    "Good morning I would like to ask about the deposit for the flat.",
    "The deposit is two hundred and fifty pounds in total.",
    "You will need to provide a passport and a bank statement.",
    "The flat is available from the first of September.",
    "There is a bus stop just outside the building.",
] * 2  # 106 words: clears completion's 80-word floor


def _seed(conn, texts=_SEED_TEXTS, name="Exam mat") -> str:
    """Insert a material built from ``texts``; returns its id."""
    from app.services.jobs import _uid, _now

    words, sentences = make_material(list(texts))
    mid = _uid()
    conn.execute(
        "INSERT INTO materials(id,name,source_type,transcript,transcript_source,"
        "words_json,sentences_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (mid, name, "upload", "\n".join(texts), "asr",
         json.dumps(words), json.dumps(sentences), _now(), _now()),
    )
    conn.commit()
    return mid


def _passport_item(words, sentences):
    start, end = sentences[2]
    target = "passport".split()
    tokens = [w["w"].lower() for w in words]
    for i in range(start, end - len(target) + 2):
        if tokens[i : i + len(target)] == target:
            return {
                "stem": "You will need to provide a ______ and a bank statement.",
                "i0": i, "i1": i + len(target) - 1,
                "answer": "passport",
                "word_limit": "ONE WORD ONLY",
                "layout": "form",
            }
    raise AssertionError("passport not found")


def _stub_llm(monkeypatch, responses_by_task: dict, capture: list | None = None):
    """Pretend a key is configured; serve canned responses by task label.

    ``responses_by_task`` maps task -> response object; every call for a
    known task gets that object, unknown tasks raise (a wrong call order
    is a bug in the test or the code under test).
    """
    monkeypatch.setattr(
        "app.routers.exam.llm_cfg_or_none", lambda _s: {"api_key": "test"}
    )

    async def fake_cached(conn, cfg, messages, *, task, **kwargs):
        if capture is not None:
            capture.append(
                {"task": task, "messages": [dict(m) for m in messages]}
            )
        if task not in responses_by_task:
            raise AssertionError(f"unexpected LLM task: {task}")
        return (
            responses_by_task[task],
            ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0),
            False,
        )

    monkeypatch.setattr(
        "app.services.exam_gen.llm.cached_chat_json", fake_cached, raising=False
    )


def _completion_llm(monkeypatch, conn, mid, capture=None):
    row = conn.execute(
        "SELECT words_json, sentences_json FROM materials WHERE id=?", (mid,)
    ).fetchone()
    words = json.loads(row["words_json"])
    sentences = json.loads(row["sentences_json"])
    _stub_llm(
        monkeypatch,
        {"exam:completion": {"groups": [
            {"title": "Housing", "items": [_passport_item(words, sentences)]}
        ]}},
        capture=capture,
    )


# ------------------------------------------------ POST persists (design §5.1)


def test_generate_persists_paper_row(client, tmp_db, monkeypatch):
    mid = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid)

    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}],
              "layout_hint": "form"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    # Task 14 shape: the paper_id arrives with persistence (§5.2).
    assert set(data) == {"paper_id", "paper", "skipped"}
    assert data["skipped"] == []
    paper_id = data["paper_id"]
    assert isinstance(paper_id, str) and paper_id

    rows = tmp_db.execute(
        "SELECT id, material_id, spec_json, paper_json, generation_json,"
        " stale, created_at FROM papers"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == paper_id
    assert row["material_id"] == mid
    assert json.loads(row["spec_json"]) == {
        "blocks": [{"type": "completion", "count": 1}],
        "layout_hint": "form",
        "regenerate": False,
    }
    # paper_json stores the whole paper dict verbatim (incl. visual slot).
    assert json.loads(row["paper_json"]) == data["paper"]
    # generation_json keeps the per-call usage accounting (Task 7 list).
    usage = json.loads(row["generation_json"])
    assert [u["task"] for u in usage] == ["exam:completion"]
    assert all("prompt_tokens" in u for u in usage)
    assert row["stale"] == 0
    assert row["created_at"]


# ------------------------------------------------------- list/detail/delete


def test_papers_list_detail_delete_roundtrip(client, tmp_db, monkeypatch):
    mid = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid)

    first = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()
    second = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()
    assert first["paper_id"] != second["paper_id"]

    # List: newest first, one summary row per stored paper.
    res = client.get(f"/api/materials/{mid}/papers")
    assert res.status_code == 200, res.text
    listing = res.json()
    assert [p["id"] for p in listing] == [
        second["paper_id"], first["paper_id"],
    ]
    summary = listing[0]
    assert set(summary) == {"id", "blocks", "item_count", "stale", "created_at"}
    assert summary["blocks"] == [{"type": "completion", "count": 1}]
    assert summary["item_count"] == 1
    assert summary["stale"] is False
    assert summary["created_at"]

    # Detail: the stored paper round-trips exactly what generation made.
    res = client.get(f"/api/papers/{first['paper_id']}")
    assert res.status_code == 200, res.text
    detail = res.json()
    assert set(detail) == {
        "id", "material_id", "spec", "paper", "stale", "created_at",
    }
    assert detail["id"] == first["paper_id"]
    assert detail["material_id"] == mid
    assert detail["spec"] == {
        "blocks": [{"type": "completion", "count": 1}],
        "layout_hint": None,
        "regenerate": False,
    }
    assert detail["paper"] == first["paper"]
    assert detail["stale"] is False

    # Delete: 204 now, 404 afterwards, list shrinks.
    assert client.delete(f"/api/papers/{first['paper_id']}").status_code == 204
    assert client.get(f"/api/papers/{first['paper_id']}").status_code == 404
    assert client.delete(f"/api/papers/{first['paper_id']}").status_code == 404
    assert [
        p["id"] for p in client.get(f"/api/materials/{mid}/papers").json()
    ] == [second["paper_id"]]


def test_papers_unknown_ids_are_404(client, tmp_db):
    assert client.get("/api/papers/missing").status_code == 404
    assert client.delete("/api/papers/missing").status_code == 404
    assert client.get("/api/materials/missing/papers").status_code == 404


def test_papers_of_two_materials_are_isolated(client, tmp_db, monkeypatch):
    mid_a = _seed(tmp_db, name="A")
    mid_b = _seed(tmp_db, name="B")
    _completion_llm(monkeypatch, tmp_db, mid_a)

    assert client.post(
        f"/api/materials/{mid_a}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).status_code == 200
    assert client.get(f"/api/materials/{mid_b}/papers").json() == []
    assert len(client.get(f"/api/materials/{mid_a}/papers").json()) == 1


# --------------------------------------------------- stale (design §5.2 语义)


def test_transcript_edit_marks_papers_stale_but_fetchable(
    client, tmp_db, monkeypatch
):
    mid = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid)
    created = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()

    # Editing the transcript (realignment path) stales every paper of
    # the material; the paper itself stays fetchable and answerable.
    res = client.put(
        f"/api/materials/{mid}/transcript",
        json={"transcript": "\n".join(_SEED_TEXTS) + "\nOne extra sentence."},
    )
    assert res.status_code == 200, res.text

    listing = client.get(f"/api/materials/{mid}/papers").json()
    assert [p["stale"] for p in listing] == [True]
    detail = client.get(f"/api/papers/{created['paper_id']}").json()
    assert detail["stale"] is True
    # Content is untouched: no hiding, no interception (§5.2).
    assert detail["paper"] == created["paper"]

    # A paper generated AFTER the edit is fresh again.
    _completion_llm(monkeypatch, tmp_db, mid)
    fresh = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()
    assert client.get(f"/api/papers/{fresh['paper_id']}").json()["stale"] is False


# --------------------------------------------- regenerate uses the real count


def test_regenerate_variation_counts_persisted_papers(client, tmp_db, monkeypatch):
    """The deferred T10 covering test: with the papers table live,
    ``_paper_count`` reads the real rows, so two regenerate requests
    carry ``variation: 1`` then ``variation: 2`` in the task frame."""
    mid = _seed(tmp_db)
    captured: list[dict] = []
    _completion_llm(monkeypatch, tmp_db, mid, capture=captured)

    for expected_variation in (1, 2):
        captured.clear()
        res = client.post(
            f"/api/materials/{mid}/exam",
            json={"blocks": [{"type": "completion", "count": 1}],
                  "regenerate": True},
        )
        assert res.status_code == 200, res.text
        assert captured, "the stub LLM must have been called"
        task_frame = captured[0]["messages"][-1]["content"]
        assert f"variation: {expected_variation}" in task_frame

    # And the count is per material, not global: a second material
    # regenerating for the first time starts at variation: 1 again.
    mid_b = _seed(tmp_db, name="B")
    captured.clear()
    _completion_llm(monkeypatch, tmp_db, mid_b, capture=captured)
    assert client.post(
        f"/api/materials/{mid_b}/exam",
        json={"blocks": [{"type": "completion", "count": 1}],
              "regenerate": True},
    ).status_code == 200
    assert "variation: 1" in captured[0]["messages"][-1]["content"]


# ------------------------------------------------------- FK cascade wiring


def test_paper_delete_cascades_attempts_chain(client, tmp_db, monkeypatch):
    """paper_attempt_items -> paper_attempts -> papers cascade on delete
    (design §5.1). Endpoints for attempts land in Task 15; the FK chain
    is exercised with direct rows."""
    from app.services.jobs import _uid, _now

    mid = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid)
    paper_id = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()["paper_id"]

    attempt_id = _uid()
    with tmp_db:
        tmp_db.execute(
            "INSERT INTO paper_attempts(id,paper_id,material_id,created_at)"
            " VALUES(?,?,?,?)",
            (attempt_id, paper_id, mid, _now()),
        )
        tmp_db.execute(
            "INSERT INTO paper_attempt_items(attempt_id,item_number,item_type,"
            "user_answer,correct,expected) VALUES(?,?,?,?,?,?)",
            (attempt_id, 1, "completion", "passport", 1, "passport"),
        )

    assert client.delete(f"/api/papers/{paper_id}").status_code == 204
    assert tmp_db.execute(
        "SELECT COUNT(*) FROM paper_attempts WHERE id=?", (attempt_id,)
    ).fetchone()[0] == 0
    assert tmp_db.execute(
        "SELECT COUNT(*) FROM paper_attempt_items WHERE attempt_id=?",
        (attempt_id,),
    ).fetchone()[0] == 0


def test_material_delete_cascades_papers(client, tmp_db, monkeypatch):
    mid = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid)
    paper_id = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()["paper_id"]
    assert client.delete(f"/api/materials/{mid}").status_code == 200
    assert client.get(f"/api/papers/{paper_id}").status_code == 404
    assert tmp_db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_material_translations_table_exists_with_composite_pk(tmp_db):
    """material_translations is created now (P6/P18 use it later): the
    material-level sentence-keyed translation snapshot table of §5.1."""
    cols = {
        r[1] for r in
        tmp_db.execute("PRAGMA table_info(material_translations)")
    }
    assert cols == {
        "material_id", "sentence_index", "src", "dst", "created_at",
    }
    # The material FK is live: rows hang off a real material.
    from app.services.jobs import _uid, _now

    mid = _uid()
    with tmp_db:
        tmp_db.execute(
            "INSERT INTO materials(id,name,source_type,transcript,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (mid, "T", "upload", "", _now(), _now()),
        )
        tmp_db.execute(
            "INSERT INTO material_translations(material_id,sentence_index,"
            "src,dst,created_at) VALUES(?,?,?,?,?)",
            (mid, 0, "hello", "你好", "2026-01-01T00:00:00+00:00"),
        )
    # Composite PK: the same (material, sentence) cannot appear twice.
    with pytest.raises(sqlite3.IntegrityError):
        with tmp_db:
            tmp_db.execute(
                "INSERT INTO material_translations(material_id,sentence_index,"
                "src,dst,created_at) VALUES(?,?,?,?,?)",
                (mid, 0, "again", "再来", "2026-01-01T00:00:00+00:00"),
            )


# ----------------------------------------------- map slot field (T13 rider)


def _map_llm(monkeypatch, conn, mid, matching):
    """Scene (step 1) + matching (step 2) canned responses, in order."""
    row = conn.execute(
        "SELECT words_json FROM materials WHERE id=?", (mid,)
    ).fetchone()
    words = json.loads(row["words_json"])
    _stub_llm(monkeypatch, {
        "scene": make_scene(words),
        "exam:map_labelling": matching,
    })


def test_map_items_carry_explicit_slot_in_persisted_paper(
    client, tmp_db, monkeypatch
):
    """Map items persist an explicit ``slot`` (the numbered blank they ask
    about); completion items carry no slot field at all."""
    words, ranges = make_material(MAP_TALK * 4)  # 228 words, spatial-rich
    from app.services.jobs import _uid, _now

    mid = _uid()
    tmp_db.execute(
        "INSERT INTO materials(id,name,source_type,transcript,transcript_source,"
        "words_json,sentences_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (mid, "Map mat", "upload", "\n".join(MAP_TALK * 4), "asr",
         json.dumps(words), json.dumps(ranges), _now(), _now()),
    )
    tmp_db.commit()

    spans = {key: find_span(words, key) for key in (
        "entrance", "gift shop", "ticket desk", "cafe", "main hall",
    )}
    matching = {"groups": [{"title": "Visitor centre", "items": [
        {"stem": "What is at blank slot 1?", "answer": "B", "slot": 1,
         "evidence": [{"i0": spans["gift shop"][0],
                       "i1": spans["gift shop"][1], "quote": "gift shop"}]},
        {"stem": "What is at blank slot 2?", "answer": "C", "slot": 2,
         "evidence": [{"i0": spans["ticket desk"][0],
                       "i1": spans["ticket desk"][1], "quote": "ticket desk"}]},
        {"stem": "What is at blank slot 3?", "answer": "D", "slot": 3,
         "evidence": [{"i0": spans["cafe"][0],
                       "i1": spans["cafe"][1], "quote": "cafe"}]},
        {"stem": "What is at blank slot 4?", "answer": "A", "slot": 4,
         "evidence": [{"i0": spans["entrance"][0],
                       "i1": spans["entrance"][1], "quote": "entrance"}]},
        {"stem": "What is at blank slot 5?", "answer": "E", "slot": 5,
         "evidence": [{"i0": spans["main hall"][0],
                       "i1": spans["main hall"][1], "quote": "main hall"}]},
    ]}]}
    _map_llm(monkeypatch, tmp_db, mid, matching)

    res = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "map_labelling", "count": 5}]},
    )
    assert res.status_code == 200, res.text
    paper_id = res.json()["paper_id"]

    stored = json.loads(tmp_db.execute(
        "SELECT paper_json FROM papers WHERE id=?", (paper_id,)
    ).fetchone()[0])
    group = stored["groups"][0]
    slots = [it["slot"] for it in group["items"]]
    assert sorted(slots) == [1, 2, 3, 4, 5]

    # Completion items never grow a slot field.
    mid2 = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid2)
    plain = client.post(
        f"/api/materials/{mid2}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()
    item = plain["paper"]["groups"][0]["items"][0]
    assert "slot" not in item
