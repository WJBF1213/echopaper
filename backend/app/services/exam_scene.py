"""Map scene reconstruction: the two-step map flow's step 1 (design §4.3).

``exam_gen`` grew past 2000 lines, so the scene half of the map block
lives here: the ``task=scene`` LLM call that turns the transcript's
spatial sentences into a drawable scene JSON, the hard validator, and the
step-2 option-pool builder (fixed node labels lettered A-F plus
transcript-mentioned distractors). Step 2 -- the question call -- stays
in ``exam_gen``'s matching flow; ``generate_paper`` feeds this module's
pool into it as the forced shared option pool.

The design's decision, kept verbatim: a structured scene JSON, not raw
SVG. Bare SVG cannot be safely validated (injection, out-of-bounds
coordinates, imprecise blank anchors) and cannot be tested; the frontend
renders the scene deterministically and every blank slot is a machine
coordinate.

Dependency direction: ``exam_gen`` imports this module at top level, so
this module may only import ``exam_gen`` *inside* functions (the shared
evidence validator and transcript helpers live there). Python executes
those deferred imports at call time, after both modules have loaded, so
the cycle never bites at import time.

Skip semantics (§4.3, 还原失败才跳过): a refused or invalid scene skips
the whole map block into ``skipped`` -- the block is never degraded into
a no-map matching task.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.services import llm, pos, prompts
from app.services.llm import LlmError

#: Accepted scene kinds (design §4.3: only the default style differs).
SCENE_KINDS = ("map", "plan", "diagram")

#: Minimum distance between two nodes, in normalized canvas units. Keeps
#: printed labels and numbered blank circles from overlapping.
MIN_NODE_DISTANCE = 8

#: The matching option-pool range (A-F) the step-2 pool must satisfy.
_POOL_MIN, _POOL_MAX = 4, 6


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


async def _scene_call(chat, conn, cfg, messages, client=None):
    """One scene-level cached call; normalizes injected-fake errors.

    Same contract as ``exam_gen._call_group`` but with the fixed
    ``scene`` task label.
    """
    try:
        return await chat(conn, cfg, messages, task="scene", client=client)
    except LlmError:
        raise
    except Exception as exc:  # network layer from an injected fake
        raise LlmError(str(exc)) from exc


def _validate_scene(
    scene: Any,
    count: int,
    words: list[dict],
    sentences: list[list[int]] | None = None,
) -> tuple[dict | None, str | None]:
    """Hard-validate an LLM scene payload (design §4.3).

    Accepts the visual shape ``{"kind": ..., "scene": {...}}``, a bare
    ``{"canvas": ..., "nodes": ...}`` body (kind defaults to ``map``),
    and runs every hard check before the scene may hang on an
    ``ExamGroup``:

      * coordinates inside the canvas; node ids unique and non-empty;
      * every node is exactly one of fixed (label required) / blank_slot;
      * blank nodes cover ``count`` with continuous numbering from 1;
      * any two nodes keep >= ``MIN_NODE_DISTANCE`` normalized units apart;
      * every node carries evidence word indices valid against ``words``
        (the same evidence validation the item validators use);
      * path endpoints reference existing node ids.

    Returns ``(visual_dict, None)`` or ``(None, reason)``; the normalized
    payload carries only known fields, so a hostile or drifting LLM
    response cannot smuggle extra keys into the paper JSON.
    """
    from app.services import exam_gen  # deferred: exam_gen imports us

    if not isinstance(scene, Mapping):
        return None, "scene 不是 JSON 对象"
    if isinstance(scene.get("scene"), Mapping):
        kind = str(scene.get("kind") or "map").strip().lower()
        body = scene["scene"]
    else:
        # A bare scene body (canvas/nodes/paths) without the wrapper.
        kind = "map"
        body = scene
    if kind not in SCENE_KINDS:
        return None, f"未知场景 kind：{kind!r}"

    canvas = body.get("canvas")
    if not isinstance(canvas, Mapping):
        return None, "scene 缺少 canvas"
    width, height = canvas.get("width"), canvas.get("height")
    if not _is_num(width) or not _is_num(height) or width <= 0 or height <= 0:
        return None, f"canvas 尺寸非法（{width!r}x{height!r}）"

    nodes_raw = body.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        return None, "scene 缺少 nodes 或 nodes 为空"

    nodes: list[dict] = []
    ids: set[str] = set()
    slots: list[int] = []
    for raw in nodes_raw:
        if not isinstance(raw, Mapping):
            return None, "节点不是 JSON 对象"
        nid = str(raw.get("id") or "").strip()
        if not nid:
            return None, "节点缺少 id"
        if nid in ids:
            return None, f"节点 id 重复：{nid}"
        ids.add(nid)
        x, y = raw.get("x"), raw.get("y")
        if not _is_num(x) or not _is_num(y):
            return None, f"节点 {nid} 坐标非法（x={x!r}, y={y!r}）"
        if not (0 <= x <= width and 0 <= y <= height):
            return None, (
                f"节点 {nid} 坐标越界（x={x}, y={y}，画布 {width}x{height}）"
            )
        shape = str(raw.get("shape") or "rect").strip().lower()
        if shape not in ("rect", "circle"):
            return None, f"节点 {nid} shape 非法：{shape!r}"
        fixed = bool(raw.get("fixed"))
        slot = raw.get("blank_slot")
        if fixed and slot is not None:
            return None, f"节点 {nid} 不能同时 fixed 和 blank_slot"
        if not fixed and slot is None:
            return None, f"节点 {nid} 既不是 fixed 也没有 blank_slot"
        if slot is not None and (
            not isinstance(slot, int) or isinstance(slot, bool) or slot < 1
        ):
            return None, f"节点 {nid} blank_slot 非法：{slot!r}"
        node: dict = {"id": nid, "x": x, "y": y, "shape": shape}
        if fixed:
            label = str(raw.get("label") or "").strip()
            if not label:
                return None, f"fixed 节点 {nid} 缺少 label"
            node["fixed"] = True
            node["label"] = label
        else:
            node["blank_slot"] = slot
            slots.append(slot)
        evidence, err = exam_gen._validate_evidence(
            raw.get("evidence"), words, sentences or []
        )
        if err:
            return None, f"节点 {nid} evidence 无效：{err}"
        node["evidence"] = [
            {"i0": e.i0, "i1": e.i1, "quote": e.quote} for e in evidence
        ]
        nodes.append(node)

    if len(slots) < count:
        return None, f"空位节点 {len(slots)} 个，少于题目数 {count}"
    if sorted(slots) != list(range(1, len(slots) + 1)):
        return None, f"blank_slot 序号必须从 1 连续编号：{sorted(slots)}"

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            dx = nodes[i]["x"] - nodes[j]["x"]
            dy = nodes[i]["y"] - nodes[j]["y"]
            if dx * dx + dy * dy < MIN_NODE_DISTANCE * MIN_NODE_DISTANCE:
                return None, (
                    f"节点 {nodes[i]['id']} 与 {nodes[j]['id']} "
                    f"距离小于 {MIN_NODE_DISTANCE}（重叠）"
                )

    paths: list[dict] = []
    for raw in body.get("paths") or []:
        if not isinstance(raw, Mapping):
            continue
        src, dst = str(raw.get("from") or ""), str(raw.get("to") or "")
        if src not in ids or dst not in ids:
            return None, f"路径引用了不存在的节点：{src!r}->{dst!r}"
        paths.append(
            {"from": src, "to": dst, "label": str(raw.get("label") or "").strip()}
        )

    visual = {
        "kind": kind,
        "scene": {
            "canvas": {"width": width, "height": height},
            "nodes": nodes,
            "paths": paths,
        },
    }
    return visual, None


async def build_scene(
    conn,
    material: Mapping,
    cfg: Any,
    *,
    locale: str,
    count: int,
    client=None,
    chat_fn=None,
    usage: list[dict] | None = None,
    ranges: list[tuple[int, int]] | None = None,
    variation: int | None = None,
) -> tuple[dict | None, str | None]:
    """Step 1 of the map flow (design §4.3): reconstruct the scene.

    One ``cached_chat_json`` call (task=``scene``) whose prompt feeds the
    block's spatial sentences ahead of the remaining content; the spatial
    cue ordering is computed here so the registry template stays dumb.
    ``ranges`` scopes the sentences to this block's audio zone (zone
    order is the block order, §4.4); ``variation`` (regenerate) appends
    the cache-busting marker like the exam calls do (§8.3).

    Returns ``(visual, None)`` or ``(None, skip_reason)``: a refusal
    quotes the model's reason, a validation failure carries the failed
    hard check, an LLM error is folded into a skip reason. The caller
    skips the whole block on ``None`` -- never a degraded no-map paper.
    """
    from app.services import exam_gen  # deferred: exam_gen imports us

    loc = "zh" if locale == "zh" else "en"
    words_json = exam_gen._material_words(material)
    sentences = exam_gen._material_sentences(material)
    if not words_json:
        reason = (
            "材料没有词表，无法还原场景"
            if loc == "zh"
            else "material has no word list; cannot reconstruct a scene"
        )
        return None, reason

    content = exam_gen.content_ranges(words_json, sentences)
    if ranges:
        wanted = {(s, e) for s, e in ranges}
        zoned = [r for r in content if r in wanted]
        if zoned:
            content = zoned
    words = [str(w.get("w", "")) for w in words_json]
    # Spatial sentences first (§4.3): the cues the rules text names are
    # the primary reconstruction material; the rest is context.
    spatial = [r for r in content if exam_gen._SPATIAL_RE.search(
        exam_gen._sentence_text(words, r[0], r[1])
    )]
    rest = [r for r in content if r not in spatial]
    sentences_text = exam_gen._render_ranges(words_json, spatial + rest)

    task_frame = prompts.render_prompt(
        conn, "scene.user", loc, sentences=sentences_text, count=count
    )
    if variation is not None:
        task_frame += f"\nvariation: {variation}"
    messages = [
        {
            "role": "system",
            "content": prompts.render_prompt(conn, "exam.system", loc),
        },
        {"role": "user", "content": task_frame},
    ]

    chat = chat_fn or llm.cached_chat_json
    try:
        obj, call_usage, from_cache = await _scene_call(
            chat, conn, cfg, messages, client
        )
    except LlmError as exc:
        reason = (
            f"场景调用失败：{exc}"
            if loc == "zh"
            else f"scene call failed: {exc}"
        )
        return None, reason
    if usage is not None:
        usage.append(
            {
                "task": "scene",
                "prompt_tokens": call_usage.prompt_tokens,
                "completion_tokens": call_usage.completion_tokens,
                "cached_tokens": call_usage.cached_tokens,
                "cached_hit": from_cache,
            }
        )

    # A refused scene is the model judging the spatial sentences do not
    # cohere into a scene (§4.5 refusal, reused verbatim).
    refusal = exam_gen._refusal_reason(obj, loc)
    if refusal is not None:
        return None, refusal

    visual, err = _validate_scene(obj, count, words_json, sentences)
    if err is not None:
        reason = (
            f"场景还原未通过校验：{err}"
            if loc == "zh"
            else f"scene failed validation: {err}"
        )
        return None, reason
    return visual, None


def map_option_pool(
    visual: Mapping,
    words_json: list[dict],
    sentences: list[list[int]],
    *,
    loc: str = "zh",
) -> tuple[list[str] | None, str | None]:
    """Step 2's forced option pool (design §4.3): the scene's fixed node
    labels, lettered A-F downstream, plus distractor labels the
    transcript mentions but the map does not carry.

    Distractors come from the existing POS candidate pool (span text),
    skipping any phrase that matches or nests inside a map label. The
    pool honours the matching 4-6 range; a transcript too thin to top
    the labels up to 4 returns ``(None, reason)`` and the block skips.
    """
    from app.services import exam_gen  # deferred: exam_gen imports us

    scene = visual.get("scene") or {}
    pool: list[str] = []
    seen: set[str] = set()
    for node in scene.get("nodes") or []:
        if not isinstance(node, Mapping) or not node.get("fixed"):
            continue
        label = str(node.get("label") or "").strip()
        norm = exam_gen._norm(label)
        if label and norm and norm not in seen:
            seen.add(norm)
            pool.append(label)
    pool = pool[:_POOL_MAX]

    target = min(_POOL_MAX, max(_POOL_MIN, len(pool) + 2))
    if len(pool) < target:
        try:
            candidates = pos.build_candidates(words_json, sentences, 48)
        except Exception:
            candidates = []
        for cand in candidates:
            if len(pool) >= target:
                break
            i0 = int(cand["i0"])
            i1 = int(cand.get("i1", i0))
            text = exam_gen._span_text(words_json, i0, i1)
            text = text.strip(exam_gen._EDGE_PUNCT).strip()
            norm = exam_gen._norm(text)
            if not norm or norm in seen:
                continue
            # "hall" nested in the map label "Main Hall" would read as a
            # duplicate option, not a distractor.
            if any(norm in s or s in norm for s in seen):
                continue
            seen.add(norm)
            pool.append(text)

    if len(pool) < _POOL_MIN:
        reason = (
            f"地图选项池不足 {len(pool)} 个（fixed 标签与干扰标签合计至少 "
            f"{_POOL_MIN} 个）"
            if loc == "zh"
            else f"map option pool has only {len(pool)} options "
            f"({_POOL_MIN} needed)"
        )
        return None, reason
    return pool, None
