"""Hybrid question generation pipeline (Task B6, spec §6).

LLM selects word-index spans; code enforces hard anchor validation; a
candidate pool (B3) fills any shortfall. Context discipline (addendum):
prompt tokens are estimated before every call; over-budget texts are
split at sentence boundaries into independent stateless per-chunk calls
and merged under GLOBAL gap/order constraints. Answers are always
verbatim transcript substrings (joined word spans).

Pure stdlib + local services; no framework imports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services import llm, pos
from app.services.llm import LlmError

MIN_GAP_WORDS = 5  # words required between two blanks
MAX_SPAN_WORDS = 3  # IELTS: 1-3 words per answer
MIN_CONFIDENCE = 0.6

ITEMS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i0": {"type": "integer"},
                    "i1": {"type": "integer"},
                    "answer": {"type": "string"},
                    "type": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["i0", "i1"],
            },
        }
    },
    "required": ["items"],
}

SYSTEM_PROMPT = (
    "你是雅思听力填空题命题专家。根据带词索引的转写文本选择挖空词跨度。"
    "规则：名词优先（真实考试约九成答案为名词）；数字与姓名适合 Section 1；"
    "每空 1-3 个词；相邻空之间至少间隔 5 个词；按文本顺序选择；"
    "避免上下文过于可猜的词；答案必须是原文逐字连续片段，不得改写。"
    "只返回 JSON 对象。"
)


class QuestionGenError(Exception):
    """Raised when no acceptable blanks can be produced at all."""


@dataclass
class Blank:
    position: int
    answer: str
    alternatives: list[str] = field(default_factory=list)
    word_start: int = 0
    word_end: int = 0
    t_start: float = 0.0
    t_end: float = 0.0
    type: str = "noun"
    word_limit: str = "ONE WORD ONLY"


@dataclass
class GeneratedSet:
    blanks: list[Blank] = field(default_factory=list)
    source: str = "fallback"  # 'llm' | 'fallback'


def derive_word_limit(n: int) -> str:
    mapping = {
        1: "ONE WORD ONLY",
        2: "NO MORE THAN TWO WORDS",
        3: "NO MORE THAN THREE WORDS",
    }
    return mapping.get(min(max(n, 1), 3), "NO MORE THAN THREE WORDS")


def _span_answer(words_json: list[dict], i0: int, i1: int) -> str:
    return " ".join(words_json[i]["w"] for i in range(i0, i1 + 1))


def validate_items(
    items: list[dict],
    words_json: list[dict],
    sentences: list[list[int]],
) -> tuple[list[dict], list[str]]:
    """Hard anchor validation (spec §6 step 3).

    Items are REORDERED by i0 (ascending), then each must satisfy:
    in bounds, span <= 3 words, answer (if given) equals the verbatim
    joined span, confidence >= 0.6, not sentence-initial, gap >= 5 words
    from the previously accepted blank.
    """
    def sort_key(it: Any):
        i0 = it.get("i0") if isinstance(it, Mapping) else None
        i1 = it.get("i1") if isinstance(it, Mapping) else None
        if not isinstance(i0, int) or not isinstance(i1, int):
            return (1 << 30, 1 << 30)
        return (i0, i1)

    ordered = sorted(
        [it for it in items if isinstance(it, Mapping)], key=sort_key
    )
    sentence_initial = {s for s, _e in sentences}
    valid: list[dict] = []
    rejected: list[str] = []
    last_end: int | None = None

    for it in ordered:
        i0, i1 = it.get("i0"), it.get("i1", it.get("i0"))
        try:
            ok = (
                isinstance(i0, int)
                and isinstance(i1, int)
                and not isinstance(i0, bool)
                and not isinstance(i1, bool)
            )
            if not ok:
                raise ValueError("i0/i1 必须是整数")
            if not (0 <= i0 <= i1 < len(words_json)):
                raise ValueError(f"索引越界（i0={i0}, i1={i1}）")
            span = i1 - i0 + 1
            if span > MAX_SPAN_WORDS:
                raise ValueError(f"跨度 {span} 词超过 {MAX_SPAN_WORDS} 词上限")
            answer = _span_answer(words_json, i0, i1)
            given = it.get("answer")
            if isinstance(given, str) and given.strip() != answer:
                raise ValueError(
                    f"答案与原文不一致（改写）：{given!r} != 原文 {answer!r}"
                )
            if i0 in sentence_initial:
                raise ValueError("句首词不可挖空")
            for w in words_json[i0 : i1 + 1]:
                p = w.get("p")
                if p is not None and p < MIN_CONFIDENCE:
                    raise ValueError(f"置信度 {p} 低于 {MIN_CONFIDENCE}")
            if last_end is not None and i0 - last_end - 1 < MIN_GAP_WORDS:
                raise ValueError(
                    f"与上一空间距不足（{i0 - last_end - 1} 词 < {MIN_GAP_WORDS}）"
                )
        except ValueError as exc:
            rejected.append(f"i0={i0} i1={i1}: {exc}")
            continue
        valid.append({**it, "i0": i0, "i1": i1, "answer": answer})
        last_end = i1
    return valid, rejected


def _cfg_value(cfg: Any, key: str, default=None):
    if isinstance(cfg, Mapping):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def _user_prompt(
    words_json: list[dict],
    a: int,
    b: int,
    candidates: list[dict],
    quota: int,
) -> str:
    lines = " ".join(
        f"{i}:{words_json[i]['w']}" for i in range(a, b + 1)
    )
    cand_hint = ", ".join(
        str(c["i0"]) for c in candidates if a <= c["i0"] <= b
    )
    return (
        f"文本词索引 {a} 到 {b}（含）：\n{lines}\n\n"
        f"候选词索引提示：{cand_hint or '无'}\n\n"
        f"请选择恰好 {quota} 个挖空跨度，返回 JSON："
        '{"items":[{"i0":起词索引,"i1":止词索引,'
        '"answer":"原文逐字答案","type":"noun|number|name|verb|adj",'
        '"reason":"简短理由"}]}'
    )


def _plan_chunks(
    words_json: list[dict],
    sentences: list[list[int]],
    candidates: list[dict],
    blank_count: int,
    budget_tokens: int,
) -> list[tuple[int, int, int]]:
    """Decide (start, end, quota) word-range chunks under the token budget.

    Single full-range chunk when it fits; otherwise pack consecutive
    sentences; an oversized sentence still becomes one chunk (cannot
    split below sentence boundaries).
    """
    total = len(words_json)
    if total == 0:
        return []
    full_prompt = _user_prompt(words_json, 0, total - 1, candidates, blank_count)
    if llm.estimate_tokens(full_prompt) + llm.PROMPT_OVERHEAD_TOKENS <= budget_tokens:
        return [(0, total - 1, blank_count)]

    chunks: list[tuple[int, int, int]] = []
    ranges = [tuple(r) for r in sentences] or [(0, total - 1)]
    # normalise/extend ranges to cover every word
    covered_end = -1
    norm: list[list[int]] = []
    for s, e in ranges:
        s = max(s, covered_end + 1)
        if e < s:
            continue
        norm.append([s, e])
        covered_end = e
    if covered_end < total - 1:
        norm.append([covered_end + 1, total - 1])

    cur: list[list[int]] = []
    for rng in norm:
        trial = cur + [rng]
        a, b = trial[0][0], trial[-1][1]
        quota = max(1, round(blank_count * (b - a + 1) / total))
        prompt = _user_prompt(words_json, a, b, candidates, quota)
        if cur and (
            llm.estimate_tokens(prompt) + llm.PROMPT_OVERHEAD_TOKENS > budget_tokens
        ):
            a0, b0 = cur[0][0], cur[-1][1]
            q0 = max(1, round(blank_count * (b0 - a0 + 1) / total))
            chunks.append((a0, b0, q0))
            cur = [rng]
        else:
            cur = trial
        if len(cur) == 1:
            # a single sentence may itself exceed the budget; flush it alone
            a1, b1 = cur[0][0], cur[0][1]
            p1 = _user_prompt(words_json, a1, b1, candidates, 1)
            if llm.estimate_tokens(p1) + llm.PROMPT_OVERHEAD_TOKENS > budget_tokens:
                q1 = max(1, round(blank_count * (b1 - a1 + 1) / total))
                chunks.append((a1, b1, q1))
                cur = []
    if cur:
        a0, b0 = cur[0][0], cur[-1][1]
        q0 = max(1, round(blank_count * (b0 - a0 + 1) / total))
        chunks.append((a0, b0, q0))
    return chunks


def _enforce_global(items: list[dict], limit: int) -> list[dict]:
    """Merge items from any number of calls: dedupe, sort, global gap, cap."""
    seen: set[tuple[int, int]] = set()
    unique = []
    for it in items:
        key = (it["i0"], it["i1"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    ordered = sorted(unique, key=lambda it: (it["i0"], it["i1"]))
    out: list[dict] = []
    last_end: int | None = None
    for it in ordered:
        if last_end is not None and it["i0"] - last_end - 1 < MIN_GAP_WORDS:
            continue
        out.append(it)
        last_end = it["i1"]
        if len(out) >= limit:
            break
    return out


def _to_blank(item: dict, words_json: list[dict], position: int) -> Blank:
    i0, i1 = item["i0"], item["i1"]
    return Blank(
        position=position,
        answer=_span_answer(words_json, i0, i1),
        alternatives=[],
        word_start=i0,
        word_end=i1,
        t_start=float(words_json[i0].get("s", 0.0)),
        t_end=float(words_json[i1].get("e", 0.0)),
        type=item.get("type") or "noun",
        word_limit=derive_word_limit(i1 - i0 + 1),
    )


async def generate_set(
    words_json: list[dict],
    sentences: list[list[int]],
    blank_count: int,
    llm_cfg: Any | None = None,
    tag_words_fn=None,
    chat_json_fn=None,
) -> GeneratedSet:
    """Full pipeline: LLM span selection -> validation -> retry -> fallback."""
    if not words_json or blank_count < 1:
        raise QuestionGenError("材料为空或空数无效，无法生成题目")

    candidates = pos.build_candidates(
        words_json, sentences, blank_count, tag_words_fn
    )

    llm_items: list[dict] = []
    used_llm = False
    if llm_cfg is not None:
        chat = chat_json_fn if chat_json_fn is not None else llm.chat_json
        max_ctx = llm.clamp_max_context(
            _cfg_value(llm_cfg, "max_context_tokens")
        )
        budget = max(0, max_ctx - llm.MAX_TOKENS - llm.PROMPT_OVERHEAD_TOKENS)
        chunks = _plan_chunks(words_json, sentences, candidates, blank_count, budget)

        rejected: list[str] = []
        for a, b, quota in chunks:
            try:
                obj = await chat(
                    llm_cfg,
                    SYSTEM_PROMPT,
                    _user_prompt(words_json, a, b, candidates, quota),
                    ITEMS_SCHEMA,
                )
            except LlmError as exc:
                rejected.append(f"LLM 调用失败：{exc}")
                continue
            items, rej = validate_items(obj.get("items", []), words_json, sentences)
            llm_items.extend(items)
            rejected.extend(rej)

        # single consolidated retry round carrying rejection reasons
        # (multi-chunk runs skip it: chunks are already independent)
        if len(chunks) == 1 and rejected and len(llm_items) < blank_count:
            base_user = _user_prompt(
                words_json, chunks[0][0], chunks[0][1], candidates, blank_count
            )
            retry_user = (
                f"{base_user}\n\n上一轮以下候选被拒绝：\n"
                + "\n".join(f"- {r}" for r in rejected)
                + "\n请避开这些问题重新选择。"
            )
            try:
                obj = await chat(llm_cfg, SYSTEM_PROMPT, retry_user, ITEMS_SCHEMA)
                items, _rej2 = validate_items(
                    obj.get("items", []), words_json, sentences
                )
                llm_items.extend(items)
            except LlmError:
                pass

    merged = _enforce_global(llm_items, blank_count)
    if merged:
        used_llm = True

    # fallback fill from the candidate pool
    if len(merged) < blank_count:
        taken_starts = {it["i0"] for it in merged}
        last_ends = sorted({it["i1"] for it in merged})
        for cand in candidates:
            if len(merged) >= blank_count:
                break
            i0 = cand["i0"]
            if i0 in taken_starts:
                continue
            conflict = False
            for it in merged:
                if i0 >= it["i0"] - MIN_GAP_WORDS and i0 <= it["i1"] + MIN_GAP_WORDS:
                    conflict = True
                    break
            if conflict:
                continue
            merged.append({"i0": i0, "i1": cand["i1"], "answer": None,
                           "type": cand["type"]})
            taken_starts.add(i0)
        merged = _enforce_global(merged, blank_count)

    if not merged:
        raise QuestionGenError(
            "无法生成题目：候选词不足或全部校验失败，请检查转写文本"
        )

    blanks = [
        _to_blank(it, words_json, pos_)
        for pos_, it in enumerate(sorted(merged, key=lambda x: x["i0"]), start=1)
    ]
    return GeneratedSet(blanks=blanks, source="llm" if used_llm else "fallback")
