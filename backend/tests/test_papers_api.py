"""Papers persistence + CRUD API tests (design §5.1/§5.2, Task 14).

``POST /api/materials/{id}/exam`` persists one ``papers`` row per
generation (spec/paper/generation JSON, stale=0) and answers
``{paper_id, paper, skipped}``; ``GET /materials/{id}/papers`` lists
summaries newest first, ``GET/DELETE /papers/{id}`` fetch and remove.
Editing the transcript marks every paper of the material stale=1 (still
fetchable). ``regenerate`` now derives its variation marker from the
REAL persisted paper count (the deferred T10 covering test). Map items
carry an explicit ``slot`` field end to end (T13 review rider).

Task 15 adds the answering loop: ``POST /papers/{id}/attempts`` grades
server-side and persists ``paper_attempts``/``paper_attempt_items``;
``GET /papers/{id}/attempts`` + ``GET /attempts/{attemptId}`` read the
history back; ``GET /papers/{id}/stats`` gives per-item accuracy (zero-
attempt items included) and the redesigned ``GET /api/stats`` aggregates
by item type across all papers.
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
        "id", "material_id", "spec", "paper", "generation", "stale",
        "created_at",
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
    # generation: the parsed per-call usage ledger (observability fix --
    # the column was written but never read).
    usage = detail["generation"]
    assert [u["task"] for u in usage] == ["exam:completion"]
    assert all(
        {"prompt_tokens", "completion_tokens", "cached_tokens"} <= set(u)
        for u in usage
    )

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


# ------------------------------------------- attempts + stats (Task 15)

# A minimal stored-shape paper with every answer kind, for the grading /
# persistence / stats endpoints. Inserted directly so the tests pin the
# API contract without re-stubbing the whole generation pipeline.
_MIXED_ITEMS = [
    {"number": 1, "type": "mcq_single", "answer": "B",
     "options": ["one", "two", "three"], "alternatives": []},
    {"number": 2, "type": "mcq_multi", "answer": "A,C", "alternatives": []},
    {"number": 3, "type": "completion", "answer": "well-known",
     "alternatives": ["well known"]},
    {"number": 4, "type": "matching", "answer": "D", "alternatives": []},
]


def _craft_paper(conn, mid, items, group_type="mixed") -> str:
    """Insert a papers row directly with a full-shape paper JSON; returns
    its id (attempts/stats read paper_json, never the generation path)."""
    from app.services.jobs import _uid, _now

    paper_id = _uid()
    paper = {
        "material_id": mid,
        "total_items": len(items),
        "warnings": [],
        "groups": [{
            "type": group_type, "title": "Crafted", "instruction": "",
            "options": [], "partial": False, "visual": None, "items": items,
        }],
    }
    with conn:
        conn.execute(
            "INSERT INTO papers(id,material_id,spec_json,paper_json,"
            "created_at) VALUES(?,?,?,?,?)",
            (paper_id, mid, json.dumps({"blocks": []}),
             json.dumps(paper), _now()),
        )
    return paper_id


def _submit(client, paper_id, answers: dict) -> dict:
    res = client.post(
        f"/api/papers/{paper_id}/attempts", json={"answers": answers}
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_submit_attempt_on_generated_paper(client, tmp_db, monkeypatch):
    """End-to-end on the real generation path: submit -> server-side
    grading -> rows in paper_attempts/paper_attempt_items."""
    mid = _seed(tmp_db)
    _completion_llm(monkeypatch, tmp_db, mid)
    paper_id = client.post(
        f"/api/materials/{mid}/exam",
        json={"blocks": [{"type": "completion", "count": 1}]},
    ).json()["paper_id"]

    data = _submit(client, paper_id, {"1": " passport "})
    assert set(data) == {"attempt_id", "created_at", "items"}
    item = data["items"][0]
    assert item == {
        "item_number": 1,
        "item_type": "completion",
        "user_answer": " passport ",
        "correct": True,
        "expected": "passport",
    }
    rows = tmp_db.execute(
        "SELECT attempt_id, item_number, item_type, user_answer, correct,"
        " expected FROM paper_attempt_items"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["attempt_id"] == data["attempt_id"]
    assert rows[0]["correct"] == 1
    assert rows[0]["expected"] == "passport"
    attempt = tmp_db.execute(
        "SELECT paper_id, material_id FROM paper_attempts WHERE id=?",
        (data["attempt_id"],),
    ).fetchone()
    assert attempt["paper_id"] == paper_id
    assert attempt["material_id"] == mid


def test_submit_attempt_grades_every_answer_kind(client, tmp_db):
    mid = _seed(tmp_db)
    paper_id = _craft_paper(tmp_db, mid, _MIXED_ITEMS)

    data = _submit(client, paper_id, {
        "1": "b",          # letter, case-insensitive
        "2": "C,A",        # multi, order-insensitive
        "3": "Well- Known",  # span, hyphen shape normalized
        "4": "A",          # matching, wrong letter
    })
    by_num = {i["item_number"]: i for i in data["items"]}
    assert [by_num[n]["correct"] for n in (1, 2, 3, 4)] == [
        True, True, True, False,
    ]
    assert by_num[3]["expected"] == "well-known"
    # user_answer round-trips exactly as submitted.
    assert by_num[1]["user_answer"] == "b"
    # Persisted flags match the response.
    flags = {
        r["item_number"]: r["correct"]
        for r in tmp_db.execute(
            "SELECT item_number, correct FROM paper_attempt_items"
        )
    }
    assert flags == {1: 1, 2: 1, 3: 1, 4: 0}


def test_submit_attempt_missing_and_unknown_answers(client, tmp_db):
    mid = _seed(tmp_db)
    paper_id = _craft_paper(tmp_db, mid, _MIXED_ITEMS)

    # Unanswered items grade wrong with user_answer None; answers for
    # item numbers that do not exist are ignored (never a 422).
    data = _submit(client, paper_id, {"4": "D", "99": "Z"})
    by_num = {i["item_number"]: i for i in data["items"]}
    assert sorted(by_num) == [1, 2, 3, 4]
    assert by_num[1]["user_answer"] is None
    assert by_num[1]["correct"] is False
    assert by_num[4]["correct"] is True
    assert tmp_db.execute(
        "SELECT COUNT(*) FROM paper_attempt_items"
    ).fetchone()[0] == 4

    # A wholly empty submission is still a valid attempt.
    empty = _submit(client, paper_id, {})
    assert [i["correct"] for i in empty["items"]] == [False] * 4


def test_attempts_404_on_unknown_paper(client, tmp_db):
    assert client.post(
        "/api/papers/missing/attempts", json={"answers": {"1": "A"}}
    ).status_code == 404
    assert client.get("/api/papers/missing/attempts").status_code == 404
    assert client.get("/api/papers/missing/stats").status_code == 404


def test_list_attempts_newest_first_with_item_count(client, tmp_db):
    mid = _seed(tmp_db)
    paper_id = _craft_paper(tmp_db, mid, _MIXED_ITEMS)
    first = _submit(client, paper_id, {"1": "B"})
    second = _submit(client, paper_id, {"1": "B", "2": "A,C"})

    res = client.get(f"/api/papers/{paper_id}/attempts")
    assert res.status_code == 200, res.text
    listing = res.json()
    assert [a["id"] for a in listing] == [second["attempt_id"], first["attempt_id"]]
    assert set(listing[0]) == {"id", "created_at", "item_count"}
    assert listing[0]["item_count"] == 4
    assert listing[0]["created_at"]

    # Isolated per paper: a second paper's attempts never leak in.
    other_id = _craft_paper(tmp_db, mid, _MIXED_ITEMS[:1])
    _submit(client, other_id, {"1": "B"})
    assert len(client.get(f"/api/papers/{other_id}/attempts").json()) == 1
    assert len(client.get(f"/api/papers/{paper_id}/attempts").json()) == 2


def test_attempt_detail_roundtrip(client, tmp_db):
    mid = _seed(tmp_db)
    paper_id = _craft_paper(tmp_db, mid, _MIXED_ITEMS)
    data = _submit(client, paper_id, {"2": "C,A"})

    res = client.get(f"/api/attempts/{data['attempt_id']}")
    assert res.status_code == 200, res.text
    detail = res.json()
    assert set(detail) == {"id", "paper_id", "material_id", "created_at", "items"}
    assert detail["id"] == data["attempt_id"]
    assert detail["paper_id"] == paper_id
    assert detail["material_id"] == mid
    assert detail["created_at"]
    assert [i["item_number"] for i in detail["items"]] == [1, 2, 3, 4]
    item2 = detail["items"][1]
    assert item2 == {
        "item_number": 2,
        "item_type": "mcq_multi",
        "user_answer": "C,A",
        "correct": True,
        "expected": "A,C",
    }
    assert client.get("/api/attempts/missing").status_code == 404


def test_paper_stats_per_item_accuracy(client, tmp_db):
    """The review page's main data: every item of the paper appears,
    zero-attempt items included; two attempts -> per-item attempts=2."""
    mid = _seed(tmp_db)
    paper_id = _craft_paper(tmp_db, mid, _MIXED_ITEMS)

    # Fresh paper: all items present with zero attempts.
    fresh = client.get(f"/api/papers/{paper_id}/stats").json()
    assert fresh == [
        {"item_number": 1, "item_type": "mcq_single", "attempts": 0, "correct": 0},
        {"item_number": 2, "item_type": "mcq_multi", "attempts": 0, "correct": 0},
        {"item_number": 3, "item_type": "completion", "attempts": 0, "correct": 0},
        {"item_number": 4, "item_type": "matching", "attempts": 0, "correct": 0},
    ]

    _submit(client, paper_id, {"1": "B"})  # item 1 right
    _submit(client, paper_id, {"1": "B", "2": "A,C", "3": "wrong"})

    stats = client.get(f"/api/papers/{paper_id}/stats").json()
    assert [(s["attempts"], s["correct"]) for s in stats] == [
        (2, 2),  # 1: right twice
        (2, 1),  # 2: right once
        (2, 0),  # 3: never right
        (2, 0),  # 4: never answered
    ]
    assert all(set(s) == {"item_number", "item_type", "attempts", "correct"}
               for s in stats)


def test_global_stats_by_type_across_papers(client, tmp_db):
    mid = _seed(tmp_db)
    paper_a = _craft_paper(tmp_db, mid, _MIXED_ITEMS)
    paper_b = _craft_paper(tmp_db, mid, [
        {"number": 1, "type": "completion", "answer": "cafe",
         "alternatives": []},
    ])

    assert client.get("/api/stats").json() == []  # nothing anywhere yet

    _submit(client, paper_a, {"1": "B", "2": "A,C", "3": "well known"})
    _submit(client, paper_a, {"1": "X"})  # everything wrong
    _submit(client, paper_b, {"1": "CAFE"})

    res = client.get("/api/stats")
    assert res.status_code == 200, res.text
    rows = {r["item_type"]: r for r in res.json()}
    assert set(rows) == {"mcq_single", "mcq_multi", "completion", "matching"}
    assert rows["mcq_single"] == {
        "item_type": "mcq_single", "attempts": 2, "correct": 1,
        "accuracy": 0.5,
    }
    # completion aggregates across BOTH papers (2 + 1 items x attempts).
    assert rows["completion"]["attempts"] == 3
    assert rows["completion"]["correct"] == 2
    assert rows["completion"]["accuracy"] == round(2 / 3, 4)
    assert rows["matching"] == {
        "item_type": "matching", "attempts": 2, "correct": 0, "accuracy": 0.0,
    }


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
