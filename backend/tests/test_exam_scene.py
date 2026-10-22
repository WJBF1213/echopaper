"""Map scene reconstruction tests (design §4.3, Task 12).

``exam_scene`` implements the two-step map flow's step 1: an LLM call
(task=``scene``) that reconstructs a drawable scene JSON from the
transcript's spatial sentences, plus the hard validator. A scene is only
accepted when every node sits inside the canvas, ids are unique, blank
slots cover the requested count with continuous numbering from 1, no two
nodes overlap (distance >= 8 normalized units) and every node carries
valid evidence word indices. A refused or invalid scene is a skip, never
a degraded no-map fallback.
"""
from __future__ import annotations

import asyncio
import json

from app.services import exam_scene
from app.services.exam_scene import (
    _validate_scene,
    build_scene,
    map_option_pool,
)
from app.services.llm import ChatUsage


MAP_TALK = [
    "Now we are standing at the entrance at the bottom of the plan.",
    "The gift shop is on the left opposite the ticket desk.",
    "The cafe is next to the main hall between the two galleries.",
    "The sculpture garden lies behind the north wing.",
    "The lecture theatre is at the end of the corridor on the right.",
]


def make_material(sentences: list[str]):
    words: list[dict] = []
    ranges: list[list[int]] = []
    idx = 0
    for text in sentences:
        start = idx
        for token in text.split():
            words.append({"w": token, "s": float(idx), "e": idx + 0.5, "p": 0.95})
            idx += 1
        ranges.append([start, idx - 1])
    return words, ranges


def as_material(words: list[dict], ranges: list[list[int]], mid: str = "m1") -> dict:
    return {
        "id": mid,
        "words_json": json.dumps(words),
        "sentences_json": json.dumps(ranges),
    }


def find_span(words: list[dict], text: str, occurrence: int = 1) -> tuple[int, int]:
    target = text.lower().split()
    tokens = [w["w"].lower().strip(".,!?;:") for w in words]
    seen = 0
    for i in range(len(tokens) - len(target) + 1):
        if tokens[i : i + len(target)] == target:
            seen += 1
            if seen == occurrence:
                return i, i + len(target) - 1
    raise AssertionError(f"span not found (occurrence {occurrence}): {text}")


def ev(words, text: str, occurrence: int = 1) -> dict:
    i0, i1 = find_span(words, text, occurrence)
    return {"i0": i0, "i1": i1, "quote": text}


def fake_cached_chat(responses, capture=None):
    """Async stub shaped like ``llm.cached_chat_json`` (3-tuple return)."""

    async def _chat(conn, cfg, messages, *, task, **kwargs):
        if capture is not None:
            capture.append({"task": task, "messages": [dict(m) for m in messages]})
        item = responses.pop(0) if responses else {"scene": None}
        if isinstance(item, tuple):
            return item
        return item, ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0), False

    return _chat


def run(coro):
    return asyncio.run(coro)


def valid_scene(words) -> dict:
    """A schema-conformant scene: 2 fixed labels + 2 blank slots."""
    return {
        "kind": "map",
        "scene": {
            "canvas": {"width": 100, "height": 70},
            "nodes": [
                {"id": "entrance", "label": "Entrance", "x": 50, "y": 66,
                 "shape": "rect", "fixed": True,
                 "evidence": [ev(words, "entrance")]},
                {"id": "gift", "label": "Gift Shop", "x": 20, "y": 30,
                 "shape": "rect", "fixed": True,
                 "evidence": [ev(words, "gift shop")]},
                {"id": "n1", "x": 80, "y": 30, "shape": "circle",
                 "blank_slot": 1, "evidence": [ev(words, "main hall")]},
                {"id": "n2", "x": 50, "y": 10, "shape": "circle",
                 "blank_slot": 2, "evidence": [ev(words, "sculpture garden")]},
            ],
            "paths": [
                {"from": "entrance", "to": "n1", "label": "Main Path"},
            ],
        },
    }


# ------------------------------------------------------------ _validate_scene


def test_valid_scene_passes_validation():
    words, ranges = make_material(MAP_TALK)
    visual, err = _validate_scene(valid_scene(words), 2, words, ranges)
    assert err is None
    scene = visual["scene"]
    assert visual["kind"] == "map"
    assert scene["canvas"] == {"width": 100, "height": 70}
    by_id = {n["id"]: n for n in scene["nodes"]}
    assert by_id["entrance"]["fixed"] is True
    assert by_id["entrance"]["label"] == "Entrance"
    assert by_id["n1"]["blank_slot"] == 1
    assert by_id["n1"].get("fixed") is None
    # Evidence is validated and normalized into the node payload.
    assert by_id["entrance"]["evidence"][0]["i0"] == find_span(words, "entrance")[0]
    assert scene["paths"] == [{"from": "entrance", "to": "n1", "label": "Main Path"}]


def test_out_of_bounds_coordinate_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)
    scene["scene"]["nodes"][1]["x"] = 120  # canvas width is 100
    visual, err = _validate_scene(scene, 2, words)
    assert visual is None
    assert "越界" in err


def test_overlapping_nodes_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)
    # Move n2 within 8 normalized units of n1 (80, 30) -> (84, 33).
    scene["scene"]["nodes"][3]["x"] = 84
    scene["scene"]["nodes"][3]["y"] = 33
    visual, err = _validate_scene(scene, 2, words)
    assert visual is None
    assert "距离" in err or "重叠" in err


def test_blank_slot_numbering_gap_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)
    # Slots 1 and 3: a gap in the printed numbered circles.
    scene["scene"]["nodes"][3]["blank_slot"] = 3
    visual, err = _validate_scene(scene, 2, words)
    assert visual is None
    assert "连续" in err

    # Numbering must start at 1, not 2.
    scene2 = valid_scene(words)
    for node in scene2["scene"]["nodes"]:
        if node.get("blank_slot"):
            node["blank_slot"] += 1
    visual, err = _validate_scene(scene2, 2, words)
    assert visual is None
    assert "连续" in err


def test_blank_slot_count_below_requested_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)  # only 2 blank slots
    visual, err = _validate_scene(scene, 5, words)
    assert visual is None
    assert "少于" in err


def test_duplicate_node_ids_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)
    scene["scene"]["nodes"][1]["id"] = "entrance"
    visual, err = _validate_scene(scene, 2, words)
    assert visual is None
    assert "重复" in err


def test_node_without_evidence_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)
    del scene["scene"]["nodes"][2]["evidence"]
    visual, err = _validate_scene(scene, 2, words)
    assert visual is None
    assert "evidence" in err

    # Evidence pointing outside the transcript is equally fatal.
    scene2 = valid_scene(words)
    scene2["scene"]["nodes"][2]["evidence"] = [{"i0": 9_999, "i1": 9_999}]
    visual, err = _validate_scene(scene2, 2, words)
    assert visual is None
    assert "evidence" in err


def test_dangling_path_endpoint_rejected():
    words, _ = make_material(MAP_TALK)
    scene = valid_scene(words)
    scene["scene"]["paths"] = [{"from": "entrance", "to": "nowhere", "label": "x"}]
    visual, err = _validate_scene(scene, 2, words)
    assert visual is None
    assert "不存在" in err


# ------------------------------------------------------- build_scene (step 1)


def test_build_scene_calls_scene_task_with_spatial_sentences_first(tmp_db):
    """Step 1 is one task='scene' call whose prompt feeds the spatial
    sentences ahead of the rest of the transcript (design §4.3)."""
    talk = MAP_TALK + ["The museum opened in nineteen sixty two after the flood."]
    words, ranges = make_material(talk)
    captured = []
    visual, err = run(build_scene(
        tmp_db, as_material(words, ranges), {"api_key": "test"},
        locale="zh", count=2,
        chat_fn=fake_cached_chat([valid_scene(words)], capture=captured),
    ))
    assert err is None
    assert visual["kind"] == "map"

    assert [c["task"] for c in captured] == ["scene"]
    messages = captured[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    prompt = messages[1]["content"]
    # The scene prompt renders from the registry and carries the count.
    assert "场景" in prompt
    assert "2" in prompt
    # Spatial sentences are fed ahead of the plain-context ones (the render
    # prefixes each word with its global index, so match bare words).
    assert prompt.index("standing") < prompt.index("nineteen")
    # The first rendered sentence is the spatial one (word index 0).
    assert "0:Now" in prompt


def test_build_scene_refused_returns_reason(tmp_db):
    words, ranges = make_material(MAP_TALK)
    captured = []
    visual, err = run(build_scene(
        tmp_db, as_material(words, ranges), {"api_key": "test"},
        locale="zh", count=2,
        chat_fn=fake_cached_chat(
            [{"refused": True, "reason": "位置关系互相矛盾"}], capture=captured,
        ),
    ))
    assert visual is None
    assert err == "位置关系互相矛盾"
    assert [c["task"] for c in captured] == ["scene"]


def test_build_scene_invalid_scene_returns_validation_reason(tmp_db):
    words, ranges = make_material(MAP_TALK)
    scene = valid_scene(words)
    scene["scene"]["nodes"][3]["x"] = 84  # overlap with n1
    scene["scene"]["nodes"][3]["y"] = 33
    visual, err = run(build_scene(
        tmp_db, as_material(words, ranges), {"api_key": "test"},
        locale="zh", count=2,
        chat_fn=fake_cached_chat([scene]),
    ))
    assert visual is None
    assert "校验" in err
    assert "距离" in err or "重叠" in err


def test_build_scene_llm_failure_becomes_skip_reason(tmp_db):
    words, ranges = make_material(MAP_TALK)

    async def boom(conn, cfg, messages, *, task, **kwargs):
        raise RuntimeError("provider down")

    visual, err = run(build_scene(
        tmp_db, as_material(words, ranges), {"api_key": "test"},
        locale="zh", count=2, chat_fn=boom,
    ))
    assert visual is None
    assert "场景调用失败" in err
    assert "provider down" in err


# ------------------------------------------------------- step-2 option pool


def test_map_option_pool_letters_fixed_labels_plus_distractors():
    words, ranges = make_material(MAP_TALK * 4)
    visual, _err = _validate_scene(valid_scene(words), 2, words, ranges)
    pool, err = map_option_pool(visual, words, ranges)
    assert err is None
    # Fixed labels come first, in map order.
    assert pool[:2] == ["Entrance", "Gift Shop"]
    # The pool satisfies the matching 4-6 option range.
    assert 4 <= len(pool) <= 6
    # Distractors come from the transcript but are not on the map.
    labels = {"entrance", "gift shop"}
    for opt in pool[2:]:
        norm = " ".join(opt.lower().split())
        assert norm not in labels
        assert norm in " ".join(w["w"].lower() for w in words)


def test_map_option_pool_caps_at_six():
    words, ranges = make_material(MAP_TALK * 4)
    scene = valid_scene(words)
    scene["scene"]["nodes"] = [
        {"id": f"f{i}", "label": f"Label {i}", "x": 10 + i * 12, "y": 30,
         "shape": "rect", "fixed": True, "evidence": [ev(words, "entrance")]}
        for i in range(7)
    ] + [
        {"id": "n1", "x": 50, "y": 60, "shape": "circle",
         "blank_slot": 1, "evidence": [ev(words, "main hall")]},
    ]
    scene["scene"]["paths"] = []  # the borrowed paths reference old ids
    visual, _err = _validate_scene(scene, 1, words, ranges)
    pool, err = map_option_pool(visual, words, ranges)
    assert err is None
    assert len(pool) == 6
    assert pool[0] == "Label 0"


def test_map_option_pool_insufficient_returns_none():
    # One fixed label over a transcript too thin for three distractors.
    words, ranges = make_material(["Hello there my friend."])
    scene = {
        "kind": "map",
        "scene": {
            "canvas": {"width": 100, "height": 70},
            "nodes": [
                {"id": "n1", "x": 50, "y": 35, "shape": "circle",
                 "blank_slot": 1, "evidence": [ev(words, "friend")]},
            ],
            "paths": [],
        },
    }
    visual, _err = _validate_scene(scene, 1, words, ranges)
    pool, err = map_option_pool(visual, words, ranges)
    assert pool is None
    assert err
