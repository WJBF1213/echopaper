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
    "你是雅思听力填空题（sentence / note completion）命题专家。"
    "输入是带词索引的转写文本，你要选出值得考的挖空跨度。\n"
    "命题规则：\n"
    "1. 答案必须是转写原文中逐字连续的一段，不得改写、翻译、缩写或补全。\n"
    "2. 每个空 1-3 个词；整段只用一个词数上限，因此不要超过 3 词。\n"
    "3. 名词或名词短语优先；数字、时间、价格、邮编、电话号码是优质答案。\n"
    "4. 专有名词（人名、地名、机构名）只有在原文中已逐字母拼读时才可以选；"
    "未拼读的专有名词一律不要选。\n"
    "5. 相邻两个空之间至少间隔 5 个词，且按原文顺序排列。\n"
    "6. 不要选：每句开头两个词、问候或告别用语、以及紧挨着取值被直接写出的标签词"
    "（例如 \"The postcode is GU7 4BX\" 中不要选 postcode，应选 GU7 4BX）。\n"
    "7. 不要选仅凭上下文就能猜出的词（固定搭配的另一半、被相邻词直接提示的词）。\n"
    "8. 优先选择需要听懂具体信息才能填对的位置，而不是语法功能词。\n"
    "只返回 JSON 对象，不要任何解释性文字。"
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


def _candidate_hint(
    words_json: list[dict],
    candidates: list[dict],
    a: int,
    b: int,
) -> str:
    """Render candidates as ``i0-i1 "text" (type)`` so phrase spans are visible.

    A bare start index hides that "railway station" is a two-word candidate;
    the model would then blank only "railway" and the validator drops it.
    """
    rows: list[str] = []
    for cand in candidates:
        i0 = cand["i0"]
        i1 = cand.get("i1", i0)
        if not (a <= i0 and i1 <= b):
            continue
        text = " ".join(words_json[k]["w"] for k in range(i0, i1 + 1))
        span = f"{i0}" if i0 == i1 else f"{i0}-{i1}"
        rows.append(f'{span} "{text}" ({cand.get("type", "noun")})')
    return "\n".join(rows) if rows else "（无）"


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
    cand_hint = _candidate_hint(words_json, candidates, a, b)
    return (
        f"文本词索引 {a} 到 {b}（含）：\n{lines}\n\n"
        f"已通过规则预筛的候选（索引 原文 类型）：\n{cand_hint}\n\n"
        f"请选择恰好 {quota} 个挖空，优先从上面的候选中选，也可以选候选之外的跨度，"
        "但必须满足系统提示里的全部规则。\n"
        "返回 JSON："
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
        # A spelled-out answer overrides the raw span ("S-A-R-A-H" -> "Sarah").
        answer=item.get("answer") or _span_answer(words_json, i0, i1),
        alternatives=list(item.get("alternatives") or []),
        word_start=i0,
        word_end=i1,
        t_start=float(words_json[i0].get("s", 0.0)),
        t_end=float(words_json[i1].get("e", 0.0)),
        type=item.get("type") or "noun",
        word_limit=item.get("word_limit") or derive_word_limit(i1 - i0 + 1),
    )


def select_fallback(
    candidates: list[dict],
    taken: list[dict],
    limit: int,
) -> list[dict]:
    """Pick up to ``limit`` extra candidates under the gap constraint.

    Candidates arrive ranked by quality (``score``). A greedy rank scan can
    take a high-scoring word that blocks two slightly lower ones; the best
    set is a maximum-weight independent set over word intervals with a
    minimum gap. Solved exactly with weighted interval scheduling in O(n*k).
    """
    if limit <= 0 or not candidates:
        return []

    taken_ranges = [
        (int(it["i0"]), int(it.get("i1", it["i0"]))) for it in taken
    ]

    def conflicts(i0: int, i1: int) -> bool:
        return any(
            i0 <= b + MIN_GAP_WORDS and i1 >= a - MIN_GAP_WORDS
            for a, b in taken_ranges
        )

    items: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for cand in candidates:
        i0 = int(cand["i0"])
        i1 = int(cand.get("i1", i0))
        key = (i0, i1)
        if key in seen or conflicts(i0, i1):
            continue
        seen.add(key)
        items.append(
            {
                **cand,
                "i0": i0,
                "i1": i1,
                "_w": int(cand.get("score", 0)),
            }
        )
    if not items:
        return []

    # Weighted interval scheduling needs items ordered by end position.
    items.sort(key=lambda c: (c["i1"], c["i0"]))
    count = len(items)
    prev = [-1] * count
    for i in range(count):
        threshold = items[i]["i0"] - MIN_GAP_WORDS - 1
        lo, hi, best = 0, i, -1
        while lo < hi:
            mid = (lo + hi) // 2
            if items[mid]["i1"] <= threshold:
                best = mid
                lo = mid + 1
            else:
                hi = mid
        prev[i] = best

    neg = -(10**9)
    best_value = [[neg] * (limit + 1) for _ in range(count + 1)]
    best_value[0][0] = 0
    for i in range(1, count + 1):
        item = items[i - 1]
        p = prev[i - 1]
        for k in range(limit + 1):
            value = best_value[i - 1][k]
            if k > 0:
                sub = best_value[p + 1][k - 1]
                if sub > neg:
                    value = max(value, sub + item["_w"])
            best_value[i][k] = value

    # Prefer filling the requested quota, then the highest total score.
    picks = max(k for k in range(limit + 1) if best_value[count][k] > neg)
    chosen: list[dict] = []
    i, k = count, picks
    while i > 0 and k > 0:
        item = items[i - 1]
        p = prev[i - 1]
        sub = best_value[p + 1][k - 1]
        if sub > neg and best_value[i][k] == sub + item["_w"]:
            chosen.append(item)
            i, k = p + 1, k - 1
        else:
            i -= 1
    chosen.reverse()
    return chosen


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

    # Final selection. LLM picks carry a large bonus so they win whenever
    # they fit, but they are not locked: two accepted picks can block each
    # other's neighbours, and appending a pool candidate then cannot reach
    # the requested count even though a different combination can. The DP
    # fills the quota first, then maximises preference, so it may swap one
    # LLM pick out to gain a slot.
    LLM_BONUS = 1000
    preferred: dict[tuple[int, int], dict] = {}
    for it in llm_items:
        key = (int(it["i0"]), int(it["i1"]))
        preferred.setdefault(key, {**it, "score": LLM_BONUS})
    used_llm = bool(preferred)

    combined: list[dict] = list(preferred.values())
    for cand in candidates:
        key = (int(cand["i0"]), int(cand.get("i1", cand["i0"])))
        if key in preferred:
            continue
        combined.append({**cand, "score": int(cand.get("score", 0))})

    merged = select_fallback(combined, [], blank_count)
    used_llm = used_llm and any(
        (int(it["i0"]), int(it["i1"])) in preferred for it in merged
    )

    if not merged:
        raise QuestionGenError(
            "无法生成题目：候选词不足或全部校验失败，请检查转写文本"
        )

    blanks = [
        _to_blank(it, words_json, pos_)
        for pos_, it in enumerate(sorted(merged, key=lambda x: x["i0"]), start=1)
    ]
    return GeneratedSet(blanks=blanks, source="llm" if used_llm else "fallback")
