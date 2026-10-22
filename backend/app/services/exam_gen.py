"""Blocks-based full paper generation (redesign §4, Task 10).

Unlike ``question_gen`` (which only selects word spans for cloze), this
module asks the LLM for complete, typed items grounded in the
transcript: the LLM must cite a word-index span, and the validator
checks the quote verbatim.

The entry point is :func:`generate_paper` with ``blocks=[{type, count}]``
in user order (design §4.4): the block order is the audio zone order,
matching keeps one shared option pool, and the finished paper is
renumbered by earliest evidence. ``completion`` carries a per-item
``word_limit`` (validated against the answer's actual word count) and a
per-item ``layout``; the printed group instruction is synthesized from
the loosest limit in the group with the official wording (§4.1).

Design constraints kept from the existing pipeline:
  * pure stdlib + local services, no framework imports;
  * every LLM call is stateless and goes through
    ``llm.cached_chat_json`` (task=``exam:<type>``); prompts come from
    the Task 5 registry;
  * exam rubrics and greetings are removed before the LLM sees the text,
    and the first/last content sentence of the material is protected
    from being blanked -- the exact failure mode of the old span-only
    prompt.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services import llm, pos, prompts
from app.services.exam_presets import QUESTION_TYPES, QuestionType
from app.services.llm import LlmError

MIN_GAP_WORDS = 5
MAX_SPAN_WORDS = 3
HEAD_WORDS = 2  # first N words of a sentence can never be the answer
MIN_CONFIDENCE = 0.6
MAX_CHUNK_WORDS = 1200

_BLANK_RE = re.compile(r"_{2,}")

# Spoken IELTS rubrics are not content. They are removed before generation;
# the validator also refuses any evidence that still points at one.
# Patterns are deliberately broad: a rubric sentence is never a test point,
# and missing one is how "You now have 30 seconds to check your answers"
# ended up as a blank in the span-only pipeline.
_RUBRIC_PATTERNS = (
    re.compile(r"^you will hear\b", re.I),
    re.compile(r"^this is the ielts listening test\b", re.I),
    re.compile(r"^test\s+\d+\s*$", re.I),
    re.compile(r"^the test is in\b.*\bparts?\b", re.I),
    re.compile(r"^all the recordings will be\b", re.I),
    re.compile(r"^there will be time\b", re.I),
    re.compile(r"^at the end of (the test|the recording)\b", re.I),
    re.compile(r"\b(transfer|write)\s+your\s+answers\b", re.I),
    re.compile(r"\banswers?\s+to\s+the\s+answer\s+sheet\b", re.I),
    re.compile(r"\bplayed\s+(only\s+)?once\b", re.I),
    re.compile(r"\bcheck\s+your\s+answers?\b", re.I),
    re.compile(r"\bquestions?\s+\d+\s+(to|and)\s+\d+\b", re.I),
    re.compile(r"^you (now )?have\b.*\b(check|answers?)\b", re.I),
    re.compile(r"^that (is|was) the end of (part|section)\b", re.I),
    re.compile(r"^(now )?turn to (part|section)\b", re.I),
    re.compile(r"^before you hear\b", re.I),
    re.compile(r"^look at questions?\b", re.I),
    re.compile(r"^you can see\b", re.I),
    re.compile(r"^there is an example\b", re.I),
    re.compile(r"^(part|section)\s+(one|two|three|four|\d+)\s*$", re.I),
    re.compile(r"^you should answer\b", re.I),
    re.compile(r"^in this (part|section)\b.*\b(hear|questions?)\b", re.I),
    re.compile(r"^now listen\b", re.I),
    re.compile(r"^\[?(pause|music|silence)\]?\.?$", re.I),
)

_GREETING_RE = re.compile(
    r"^(good\s+(morning|afternoon|evening)|hello|hi|hey|welcome|"
    r"nice\s+to\s+meet\s+you|how\s+are\s+you|how\s+do\s+you\s+do)\b",
    re.I,
)
_CLOSING_RE = re.compile(
    r"^(thank\s+you|thanks|cheers|bye|goodbye|see\s+you|"
    r"have\s+a\s+(nice|good)\s+day|you'?re\s+welcome)\b",
    re.I,
)


_NUMBER_WORDS = frozenset(
    """
    zero one two three four five six seven eight nine ten eleven twelve
    thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty
    thirty forty fifty sixty seventy eighty ninety hundred thousand million
    billion and point oh double
    """.split()
)


def _counts_as_number(words_json: list[dict], i0: int, i1: int) -> bool:
    """IELTS treats a numeric answer as one unit even when spelled out.

    "250" and "two hundred and fifty" are both "a number" under
    ONE WORD AND/OR A NUMBER; only non-numeric words consume the word budget.
    """
    tokens = [
        str(words_json[i].get("w", "")).strip(_EDGE_PUNCT).lower()
        for i in range(i0, i1 + 1)
    ]
    if not tokens:
        return False
    if all(t in _NUMBER_WORDS or any(ch.isdigit() for ch in t) for t in tokens):
        return True
    return False


class ExamGenError(Exception):
    """Raised when a paper cannot be produced at all."""


# ------------------------------------------------------- per-type paper data
# The six-key registry (design §4.2) carries identity data only; the
# answer-shape knobs the validators need and the fixed paper
# instructions live here, keyed off the type / answer kind.

#: Official printed instructions for the fixed-limit types. completion
#: synthesizes its group instruction from the items' word limits (§4.1).
_INSTRUCTIONS: dict[str, str] = {
    "mcq_single": "Choose the correct letter, A, B or C.",
    "mcq_multi": "Choose TWO letters, A-E.",
    "matching": "Match each item with the correct option, A-F.",
    "map_labelling": "Label the map below. Write the correct letter, A-F.",
    "short_answer": (
        "Answer the questions below. Write NO MORE THAN THREE WORDS "
        "for each answer."
    ),
}

#: The task-frame instruction shown to the LLM while writing completion
#: items. The printed line is synthesized after validation; this is the
#: loosest possible example, so no per-item limit contradicts it.
_COMPLETION_TASK_INSTRUCTION = (
    "Complete the notes below. Write NO MORE THAN THREE WORDS "
    "for each answer."
)

_GENERIC_INSTRUCTION = "Answer the questions below."


def _options_range(qtype: QuestionType) -> tuple[int, int]:
    """(min, max) printed options per answer kind (legacy registry data)."""
    return {
        "option": (3, 3),
        "option_multi": (5, 5),
        "matching": (4, 6),
    }.get(qtype.answer_kind, (0, 0))


def _multi_count(qtype: QuestionType) -> int:
    return 2 if qtype.answer_kind == "option_multi" else 1


#: The per-item completion word limits (design §4.1) and the word budget
#: each one grants. IELTS counts a whole number as one word.
_WORD_LIMIT_WORDS: dict[str, int] = {
    "ONE WORD ONLY": 1,
    "NO MORE THAN TWO WORDS": 2,
    "NO MORE THAN THREE WORDS": 3,
}
SHORT_ANSWER_WORD_LIMIT = "NO MORE THAN THREE WORDS"


def _parse_word_limit(raw: Any) -> str | None:
    """Canonical limit text or None. Tolerates case and the official
    "AND/OR A NUMBER" suffix; anything else is unparsable."""
    text = str(raw or "").strip().upper().rstrip(".")
    text = re.sub(r"\s*AND/OR\s+A\s+NUMBER\s*$", "", text)
    for canonical in _WORD_LIMIT_WORDS:
        noun = canonical.replace("NO MORE THAN ", "").replace(" ONLY", "")
        if text in (canonical, noun):
            return canonical
    return None


def _limit_for_words(words: int) -> str:
    for canonical, budget in sorted(
        _WORD_LIMIT_WORDS.items(), key=lambda kv: kv[1]
    ):
        if words <= budget:
            return canonical
    return "NO MORE THAN THREE WORDS"


#: Official instruction nouns per completion layout (design §4.1: the
#: layout names the thing being completed; sentence prints plural).
_LAYOUT_NOUNS: dict[str, str] = {
    "form": "the form below",
    "table": "the table below",
    "notes": "the notes below",
    "sentence": "the sentences below",
    "summary": "the summary below",
    "flowchart": "the flow-chart below",
}
DEFAULT_LAYOUT = "notes"


def _item_layout(
    qtype: QuestionType,
    raw: Mapping,
    group_layout: str = "",
    layout_hint: str | None = None,
) -> str | None:
    """Resolve a completion item's layout: the forced hint wins, then the
    item's own suggestion, then the group's, then the generic notes."""
    if not qtype.layouts:
        return None
    if layout_hint:
        return layout_hint
    for candidate in (raw.get("layout"), group_layout):
        text = str(candidate or "").strip().lower()
        if text in qtype.layouts:
            return text
    return DEFAULT_LAYOUT


def _group_instruction(qtype: QuestionType, items: list["ExamItem"]) -> str:
    """The printed instruction for one group (design §4.1)."""
    if qtype.key == "completion" and items:
        loosest = max(
            _WORD_LIMIT_WORDS.get(it.word_limit, 1) for it in items
        )
        noun = _LAYOUT_NOUNS.get(items[0].layout or "", "the notes below")
        return (
            f"Complete {noun}. Write {_limit_for_words(loosest)} "
            "for each answer."
        )
    return _INSTRUCTIONS.get(qtype.key, _GENERIC_INSTRUCTION)


@dataclass
class ExamContext:
    """Facts about the transcript computed once per paper (not per item)."""

    words: list[str]
    spelled_runs: list[dict]
    sentence_of: list[int]
    sentence_starts: dict[int, int]


def build_context(words_json: list[dict], sentences: list[list[int]]) -> ExamContext:
    words = [str(w.get("w", "")) for w in words_json]
    runs, _covered_words = pos.spelling_runs(words)
    starts = _sentence_starts(words_json, sentences)
    where = [0] * len(words)
    for si, (s, e) in enumerate(normalize_ranges(len(words), sentences)):
        for i in range(s, e + 1):
            where[i] = si
    return ExamContext(
        words=words,
        spelled_runs=runs,
        sentence_of=where,
        sentence_starts={s: si for si, (s, _e) in enumerate(normalize_ranges(len(words), sentences))},
    )


def _looks_like_name(ctx: ExamContext, i0: int, i1: int) -> bool:
    """Mid-sentence Title Case tokens are proper names (not weekdays/months)."""
    temporal = {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    }
    start = ctx.sentence_starts.get(ctx.sentence_of[i0], 0)
    for i in range(i0, i1 + 1):
        token = ctx.words[i].strip(_EDGE_PUNCT)
        if not token:
            continue
        if i < start + HEAD_WORDS:
            continue
        if token.lower() in temporal:
            continue
        if token[:1].isupper() and token[1:].islower():
            return True
    return False


def _unfair_name_answer(ctx: ExamContext, i0: int, i1: int) -> bool:
    """An unspelled proper name cannot be written down correctly from audio.

    "Home Solutions" is unanswerable unless the speaker spells it; the old
    candidate pool already drops these, and the typed generator must too.
    """
    if not _looks_like_name(ctx, i0, i1):
        return False
    joined = " ".join(ctx.words[i0 : i1 + 1])
    return not pos.is_spelled(joined, ctx.spelled_runs)


# --------------------------------------------------------------------- model


@dataclass
class Evidence:
    i0: int
    i1: int
    quote: str
    t_start: float = 0.0
    t_end: float = 0.0

    def to_dict(self) -> dict:
        return {
            "i0": self.i0,
            "i1": self.i1,
            "quote": self.quote,
            "t_start": self.t_start,
            "t_end": self.t_end,
        }


@dataclass
class ExamItem:
    number: int
    type_key: str
    stem: str
    answer: str
    options: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    word_limit: str | None = None
    # Presentation layout (completion only, design §4.1); None elsewhere.
    layout: str | None = None
    label: str = ""
    alternatives: list[str] = field(default_factory=list)
    group_title: str = ""
    # Text of the keyed option, for matching types. The letter alone is not
    # stable when two chunks carry different option pools.
    answer_text: str = ""

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "type": self.type_key,
            "stem": self.stem,
            "answer": self.answer,
            "options": self.options,
            "evidence": [e.to_dict() for e in self.evidence],
            "word_limit": self.word_limit,
            "layout": self.layout,
            "label": self.label,
            "alternatives": self.alternatives,
            "group_title": self.group_title,
            "answer_text": self.answer_text,
        }


@dataclass
class ExamGroup:
    type_key: str
    title: str
    instruction: str
    items: list[ExamItem] = field(default_factory=list)
    # Shared option pool for matching; empty for other types.
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type_key,
            "title": self.title,
            "instruction": self.instruction,
            "options": self.options,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class ExamPaper:
    material_id: str
    groups: list[ExamGroup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return sum(len(g.items) for g in self.groups)

    def to_dict(self) -> dict:
        return {
            "material_id": self.material_id,
            "total_items": self.total_items,
            "warnings": self.warnings,
            "groups": [g.to_dict() for g in self.groups],
        }


@dataclass
class GenerateResult:
    """What one ``generate_paper`` call produced (design §5.2).

    ``paper`` is the printable paper dict (``ExamPaper.to_dict`` shape).
    ``skipped`` lists refused blocks ``[{type, reason}]`` (design §4.5);
    it stays empty until the refusal path lands (Task 11) but the API
    contract already carries it. ``usage`` records every block-level
    ``cached_chat_json`` call with its task label and cache-hit flag
    (Task 7 accounting).
    """

    paper: dict
    skipped: list[dict] = field(default_factory=list)
    usage: list[dict] = field(default_factory=list)


# ------------------------------------------------------------- text helpers


def _sentence_text(words: list[str], s: int, e: int) -> str:
    return " ".join(words[s : e + 1]).strip()


def is_rubric(text: str) -> bool:
    return any(p.search(text) for p in _RUBRIC_PATTERNS)


def _is_formulaic(text: str) -> bool:
    """A short pure greeting/sign-off, not a content sentence that opens politely."""
    stripped = text.strip()
    if len(stripped.split()) > 8:
        return False
    return bool(_GREETING_RE.search(stripped) or _CLOSING_RE.search(stripped))


def normalize_ranges(n: int, sentences: list[list[int]]) -> list[tuple[int, int]]:
    """Cover every word exactly once; tolerate gaps/overlaps in the input."""
    ranges: list[tuple[int, int]] = []
    covered = -1
    for raw in sentences or []:
        try:
            s, e = int(raw[0]), int(raw[1])
        except (TypeError, ValueError, IndexError):
            continue
        s = max(s, covered + 1)
        e = min(e, n - 1)
        if e < s:
            continue
        ranges.append((s, e))
        covered = e
    if covered < n - 1:
        ranges.append((covered + 1, n - 1))
    return ranges


def content_ranges(words_json: list[dict], sentences: list[list[int]]) -> list[tuple[int, int]]:
    """Sentence ranges that carry testable content (rubrics removed)."""
    words = [str(w.get("w", "")) for w in words_json]
    out: list[tuple[int, int]] = []
    for s, e in normalize_ranges(len(words), sentences):
        text = _sentence_text(words, s, e)
        if not text or is_rubric(text) or _is_formulaic(text):
            continue
        out.append((s, e))
    return out


def _render_ranges(words_json: list[dict], ranges: list[tuple[int, int]]) -> str:
    lines: list[str] = []
    for s, e in ranges:
        toks = " ".join(
            f"{i}:{words_json[i].get('w', '')}" for i in range(s, e + 1)
        )
        lines.append(f"[{s}-{e}] {toks}")
    return "\n".join(lines)


def _span_text(words_json: list[dict], i0: int, i1: int) -> str:
    return " ".join(str(words_json[i].get("w", "")) for i in range(i0, i1 + 1))


_EDGE_PUNCT = ".,!?;:\"'()[]{}"


def _answer_text(words_json: list[dict], i0: int, i1: int) -> str:
    """Verbatim span with sentence punctuation trimmed from both ends.

    ASR writes "September." as one token; the answer key must read
    "September" while the evidence quote keeps the transcript verbatim.
    """
    return _span_text(words_json, i0, i1).strip().strip(_EDGE_PUNCT).strip()


def _norm(text: str) -> str:
    text = text.replace("\u2019", "'").lower()
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentence_starts(words_json: list[dict], sentences: list[list[int]]) -> set[int]:
    return {s for s, _e in normalize_ranges(len(words_json), sentences)}


def _covered(i: int, ranges: list[tuple[int, int]]) -> bool:
    return any(s <= i <= e for s, e in ranges)


# --------------------------------------------------------------- LLM schema


def _schema_hint(qtype: QuestionType) -> str:
    if qtype.answer_kind == "span":
        if qtype.key == "completion":
            # Per-item word_limit + layout (design §4.1); the group may
            # also suggest one layout for all its items.
            return (
                '{"groups":[{"title":"...","layout":"notes",'
                '"items":[{"stem":"... ______ ...","label":"...",'
                '"i0":12,"i1":12,"answer":"...",'
                '"word_limit":"ONE WORD ONLY","layout":"form",'
                '"reason":"..."}]}]}'
            )
        return (
            '{"groups":[{"title":"...","items":[{"stem":"... ______ ...",'
            '"label":"...","i0":12,"i1":12,"answer":"...","reason":"..."}]}]}'
        )
    if qtype.answer_kind == "matching":
        return (
            '{"groups":[{"title":"...","options":["...","..."],'
            '"items":[{"stem":"...","answer":"A",'
            '"evidence":[{"i0":12,"i1":18,"quote":"..."}],"reason":"..."}]}]}'
        )
    letters = "A,C" if qtype.answer_kind == "option_multi" else "A"
    return (
        '{"groups":[{"title":"...","items":[{"stem":"...",'
        '"options":["...","...","..."],"answer":"%s",'
        '"evidence":[{"i0":12,"i1":18,"quote":"..."}],"reason":"..."}]}]}'
        % letters
    )


# ----------------------------------------------------------------- prompts
# All prompt texts live in the Task 5 registry (app/services/prompts.py);
# _build_messages assembles the three-part layout of design §8.1 with the
# prefix ordered by stability: system (global) -> stable frame (per
# material: transcript + candidates) -> task frame (per request: type
# rules, count, JSON schema hint, and -- only for regenerate=True -- the
# variation marker that busts the local llm_cache key, §8.3).


def _type_name(qtype: QuestionType, lang: str) -> str:
    """Localized type name from the registry's two name fields."""
    return qtype.name_zh if lang == "zh" else qtype.name_en


def _task_instruction(qtype: QuestionType) -> str:
    """The instruction line shown to the LLM in the task frame."""
    if qtype.key == "completion":
        return _COMPLETION_TASK_INSTRUCTION
    return _INSTRUCTIONS.get(qtype.key, _GENERIC_INSTRUCTION)


def _rules_text(conn, qtype: QuestionType, lang: str) -> str:
    """Per-type rules text from the prompt registry (overrides apply)."""
    return prompts.render_prompt(conn, f"exam.rules.{qtype.key}", lang)


# -------------------------------------------------------------- validation


def _token_norms(words_json: list[dict]) -> list[str]:
    return [_norm(str(w.get("w", ""))) for w in words_json]


def _align_tokens(
    words_json: list[dict],
    target: str,
    lo: int,
    hi: int,
) -> tuple[int, int] | None:
    """Find ``target`` as a contiguous word span inside ``[lo, hi]``.

    Item writers frequently quote "the council have provided special signs"
    while returning indices that include a trailing "but", or omit a leading
    "well". The transcript is the source of truth, so the text is located
    first and the indices are snapped to it.
    """
    tokens = [_norm(t) for t in target.split() if _norm(t)]
    if not tokens:
        return None
    words = _token_norms(words_json)
    lo = max(0, lo)
    hi = min(len(words) - 1, hi)
    for start in range(lo, hi - len(tokens) + 2):
        end = start + len(tokens) - 1
        if end > hi:
            break
        if words[start : end + 1] == tokens:
            return start, end
    return None


def _snap_span(
    words_json: list[dict], i0: int, i1: int, text: str, margin: int = 4
) -> tuple[int, int] | None:
    """Align ``text`` near ``[i0, i1]``; None when it is not there."""
    lo = max(0, i0 - margin)
    hi = min(len(words_json) - 1, i1 + margin)
    return _align_tokens(words_json, text, lo, hi)


def _validate_evidence(
    raw: Any,
    words_json: list[dict],
    sentences: list[list[int]],
) -> tuple[list[Evidence], str | None]:
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return [], "缺少 evidence 词跨度"
    words = [str(w.get("w", "")) for w in words_json]
    starts = _sentence_starts(words_json, sentences)
    out: list[Evidence] = []
    for ev in raw:
        if not isinstance(ev, Mapping):
            return [], "evidence 不是对象"
        i0, i1 = ev.get("i0"), ev.get("i1", ev.get("i0"))
        if (
            not isinstance(i0, int)
            or isinstance(i0, bool)
            or not isinstance(i1, int)
            or isinstance(i1, bool)
            or not (0 <= i0 <= i1 < len(words_json))
        ):
            return [], f"evidence 索引越界（i0={i0}, i1={i1}）"
        quote = str(ev.get("quote") or "").strip()
        if quote:
            snapped = _snap_span(words_json, i0, i1, quote)
            if snapped is None:
                return [], f"evidence 引文不在原文该位置附近：{quote!r}"
            i0, i1 = snapped
        actual = _span_text(words_json, i0, i1)
        if quote and _norm(quote) != _norm(actual):
            return [], f"evidence 引文与原文不一致：{quote!r} != {actual!r}"
        s = next((s for s, e in normalize_ranges(len(words), sentences) if s <= i0 <= e), 0)
        text = _sentence_text(words, s, max(s, i1))
        if is_rubric(text):
            return [], "evidence 落在考试指令句中"
        out.append(
            Evidence(
                i0=i0,
                i1=i1,
                quote=quote or actual,
                t_start=float(words_json[i0].get("s", 0.0) or 0.0),
                t_end=float(words_json[i1].get("e", 0.0) or 0.0),
            )
        )
    return out, None


def _canonical_option(answer: str, options: list[str]) -> str | None:
    """Map an answer (letter, letter+text, or full text) to its letter."""
    raw = (answer or "").strip()
    if not raw:
        return None
    letters = "ABCDEFGH"
    m = re.match(r"^([A-H])\b", raw.upper())
    if m and len(raw) <= 2:
        idx = letters.index(m.group(1))
        return m.group(1) if idx < len(options) else None
    norm = _norm(raw)
    for idx, opt in enumerate(options):
        if norm == _norm(opt):
            return letters[idx]
    # "A. some text" / "A - some text"
    if m:
        idx = letters.index(m.group(1))
        if idx < len(options):
            return m.group(1)
    return None


def _canonical_multi(answer: str, options: list[str], count: int) -> str | None:
    parts = [p for p in re.split(r"[,;/&]|\band\b", answer or "") if p.strip()]
    letters: list[str] = []
    for part in parts:
        letter = _canonical_option(part, options)
        if letter is None:
            return None
        if letter not in letters:
            letters.append(letter)
    if len(letters) != count:
        return None
    return ",".join(sorted(letters))


def _subspan(
    words_json: list[dict], i0: int, i1: int, answer: str
) -> tuple[int, int] | None:
    """Locate ``answer`` as a contiguous sub-span of ``[i0, i1]``.

    Item writers routinely mark "make furniture" as the evidence phrase but
    key only "furniture". Shrinking keeps the answer verbatim instead of
    failing the item -- but the shrunk span is re-validated afterwards.
    """
    target = [_norm(t) for t in answer.split() if _norm(t)]
    if not target or len(target) > i1 - i0 + 1:
        return None
    tokens = [_norm(str(words_json[i].get("w", ""))) for i in range(i0, i1 + 1)]
    for start in range(len(tokens) - len(target) + 1):
        if tokens[start : start + len(target)] == target:
            return i0 + start, i0 + start + len(target) - 1
    return None


def _nested_answer(answer: str, taken: list[str]) -> str | None:
    """Return the already-used answer that contains this one as whole words.

    "warehouse assistant" followed by "assistant" is the same listening point
    twice. Comparison is token-based: "ash" must not match the "ashes" inside
    a different answer.
    """
    tokens = _norm(answer).split()
    if not tokens:
        return None
    for prior in taken:
        other = _norm(prior).split()
        if not other or other == tokens:
            continue
        if len(tokens) < len(other):
            if any(other[i : i + len(tokens)] == tokens for i in range(len(other) - len(tokens) + 1)):
                return prior
        elif any(tokens[i : i + len(other)] == other for i in range(len(tokens) - len(other) + 1)):
            return prior
    return None


def _validate_completion(
    raw: Mapping,
    words_json: list[dict],
    sentences: list[list[int]],
    qtype: QuestionType,
    allowed: list[tuple[int, int]],
    ctx: ExamContext,
    group_layout: str = "",
    layout_hint: str | None = None,
) -> tuple[ExamItem | None, str | None]:
    # Per-item word limit (design §4.1): completion declares it on every
    # item; short_answer keeps the fixed 3-word limit.
    if qtype.key == "completion":
        word_limit = _parse_word_limit(raw.get("word_limit"))
        if word_limit is None:
            return None, (
                f"word_limit 缺失或无法识别：{raw.get('word_limit')!r}"
            )
    else:
        word_limit = SHORT_ANSWER_WORD_LIMIT
    limit_words = _WORD_LIMIT_WORDS[word_limit]

    words = [str(w.get("w", "")) for w in words_json]
    i0, i1 = raw.get("i0"), raw.get("i1", raw.get("i0"))
    if (
        not isinstance(i0, int)
        or isinstance(i0, bool)
        or not isinstance(i1, int)
        or isinstance(i1, bool)
        or not (0 <= i0 <= i1 < len(words_json))
    ):
        return None, f"答案索引越界（i0={i0}, i1={i1}）"
    if i1 - i0 + 1 > MAX_SPAN_WORDS:
        return None, f"答案跨度 {i1 - i0 + 1} 词，超过 {MAX_SPAN_WORDS} 词"

    given = str(raw.get("answer") or "").strip()
    span_text = _span_text(words_json, i0, i1)
    if given and _norm(given) != _norm(span_text):
        # The writer may quote a phrase but key one adjacent word ("312" next
        # to "BC"), or the reverse. Locate the answer near the indices first.
        snapped = _snap_span(words_json, i0, i1, given)
        if snapped is not None:
            i0, i1 = snapped
        else:
            shrunk = _subspan(words_json, i0, i1, given)
            if shrunk is None:
                return None, f"答案不是逐字原文：{given!r} != {span_text!r}"
            i0, i1 = shrunk
        span_text = _span_text(words_json, i0, i1)

    if not _covered(i0, allowed):
        return None, "答案落在开头/结尾保护句或考试指令中"

    if _unfair_name_answer(ctx, i0, i1):
        return None, "未拼读的专有名词，考生无法确定拼写"

    starts = _sentence_starts(words_json, sentences)
    owner = next(
        ((s, e) for s, e in normalize_ranges(len(words), sentences) if s <= i0 <= e),
        None,
    )
    if owner is not None and i0 < owner[0] + HEAD_WORDS:
        return None, "答案位于句首两词内"
    for w in words_json[i0 : i1 + 1]:
        p = w.get("p")
        if p is not None and float(p) < MIN_CONFIDENCE:
            return None, f"ASR 置信度 {p} 低于 {MIN_CONFIDENCE}"

    answer = _answer_text(words_json, i0, i1)
    if given and _norm(given) != _norm(answer):
        return None, f"答案不是逐字原文：{given!r} != {answer!r}"
    # The limit is checked against the FINAL answer span (a snapped/shrunk
    # span can differ from the indices the writer returned), with the
    # IELTS number rule: a whole number phrase counts as one word.
    counted = 1 if _counts_as_number(words_json, i0, i1) else i1 - i0 + 1
    if counted > limit_words:
        return None, (
            f"答案 {counted} 词，超过该题 word_limit（{word_limit}）"
        )

    stem = str(raw.get("stem") or "").strip()
    if not stem:
        return None, "缺少题干 stem"
    if not _BLANK_RE.search(stem):
        return None, "题干缺少 ______ 挖空标记"
    if _norm(answer) and _norm(answer) in _norm(_BLANK_RE.sub(" ", stem)):
        return None, "题干泄露了答案"
    label = str(raw.get("label") or "").strip()
    if label:
        label_tokens = _norm(label).split()
        answer_tokens = _norm(answer).split()
        if answer_tokens and any(
            label_tokens[i : i + len(answer_tokens)] == answer_tokens
            for i in range(len(label_tokens) - len(answer_tokens) + 1)
        ):
            return None, f"字段标签 {label!r} 泄露了答案"

    evidence = [
        Evidence(
            i0=i0,
            i1=i1,
            quote=answer,
            t_start=float(words_json[i0].get("s", 0.0) or 0.0),
            t_end=float(words_json[i1].get("e", 0.0) or 0.0),
        )
    ]
    return (
        ExamItem(
            number=0,
            type_key=qtype.key,
            stem=stem,
            answer=answer,
            evidence=evidence,
            word_limit=word_limit,
            layout=_item_layout(qtype, raw, group_layout, layout_hint),
            label=str(raw.get("label") or "").strip(),
            group_title=str(raw.get("group_title") or ""),
        ),
        None,
    )


def _validate_option_item(
    raw: Mapping,
    words_json: list[dict],
    sentences: list[list[int]],
    qtype: QuestionType,
) -> tuple[ExamItem | None, str | None]:
    stem = str(raw.get("stem") or "").strip()
    if not stem:
        return None, "缺少题干 stem"
    options = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()]
    lo, hi = _options_range(qtype)
    expected = lo if lo == hi else None
    if expected is not None and len(options) != expected:
        return None, f"选项数 {len(options)}，应为 {expected}"
    if not (lo <= len(options) <= hi):
        return None, f"选项数 {len(options)} 超出 {lo}-{hi}"
    if len({_norm(o) for o in options}) != len(options):
        return None, "选项重复"

    if qtype.answer_kind == "option_multi":
        answer = _canonical_multi(str(raw.get("answer") or ""), options, _multi_count(qtype))
    else:
        answer = _canonical_option(str(raw.get("answer") or ""), options)
    if answer is None:
        return None, f"答案无法对应到选项：{raw.get('answer')!r}"

    evidence, err = _validate_evidence(raw.get("evidence"), words_json, sentences)
    if err:
        return None, err
    return (
        ExamItem(
            number=0,
            type_key=qtype.key,
            stem=stem,
            answer=answer,
            options=options,
            evidence=evidence,
            word_limit=None,
            group_title=str(raw.get("group_title") or ""),
        ),
        None,
    )


def _validate_matching_item(
    raw: Mapping,
    options: list[str],
    words_json: list[dict],
    sentences: list[list[int]],
    qtype: QuestionType,
) -> tuple[ExamItem | None, str | None]:
    stem = str(raw.get("stem") or "").strip()
    if not stem:
        return None, "缺少题干 stem"
    # A matching stem that repeats the option text is answerable by string
    # comparison ("Which aspect involves considering <option text>?").
    stem_norm = _norm(stem)
    for opt in options:
        opt_norm = _norm(re.sub(r"^[A-H][.)]\s*", "", opt))
        if opt_norm and len(opt_norm.split()) >= 2 and opt_norm in stem_norm:
            return None, f"题干复述了选项原文，题目可被直接匹配：{opt!r}"
    answer = _canonical_option(str(raw.get("answer") or ""), options)
    if answer is None:
        return None, f"答案无法对应到选项：{raw.get('answer')!r}"
    evidence, err = _validate_evidence(raw.get("evidence"), words_json, sentences)
    if err:
        return None, err
    return (
        ExamItem(
            number=0,
            type_key=qtype.key,
            stem=stem,
            answer=answer,
            options=list(options),
            evidence=evidence,
            word_limit=None,
            group_title=str(raw.get("group_title") or ""),
            answer_text=options["ABCDEFGH".index(answer)],
        ),
        None,
    )


def _enforce_gap(items: list[ExamItem], limit: int) -> tuple[list[ExamItem], list[str]]:
    """Listening order + minimum gap for completion answers."""
    ordered = sorted(items, key=lambda it: (it.evidence[0].i0, it.evidence[0].i1))
    out: list[ExamItem] = []
    warnings: list[str] = []
    last_end: int | None = None
    for item in ordered:
        i0 = item.evidence[0].i0
        i1 = item.evidence[0].i1
        if last_end is not None and i0 - last_end - 1 < MIN_GAP_WORDS:
            warnings.append(
                f"丢弃与上一题过近的题目（{i0 - last_end - 1} 词 < {MIN_GAP_WORDS}）"
            )
            continue
        out.append(item)
        last_end = i1
        if len(out) >= limit:
            break
    return out, warnings


# --------------------------------------------------------------- generation


def _candidate_hint(
    words_json: list[dict],
    sentences: list[list[int]],
    allowed: list[tuple[int, int]],
    count: int,
) -> str:
    try:
        pool = pos.build_candidates(words_json, sentences, max(8, count * 3))
    except Exception:
        return "（无）"
    rows: list[str] = []
    for cand in pool:
        i0 = int(cand["i0"])
        i1 = int(cand.get("i1", i0))
        if not _covered(i0, allowed) or not _covered(i1, allowed):
            continue
        text = _span_text(words_json, i0, i1)
        span = f"{i0}" if i0 == i1 else f"{i0}-{i1}"
        rows.append(f'{span} "{text}" ({cand.get("type", "noun")})')
        if len(rows) >= 40:
            break
    return "\n".join(rows) if rows else "（无）"


def _pack_ranges(
    ranges: list[tuple[int, int]], max_words: int = MAX_CHUNK_WORDS
) -> list[list[tuple[int, int]]]:
    chunks: list[list[tuple[int, int]]] = []
    cur: list[tuple[int, int]] = []
    size = 0
    for s, e in ranges:
        length = e - s + 1
        if cur and size + length > max_words:
            chunks.append(cur)
            cur, size = [], 0
        cur.append((s, e))
        size += length
    if cur:
        chunks.append(cur)
    return chunks or [ranges]


def _split_for_coverage(
    chunks: list[list[tuple[int, int]]], parts: int
) -> list[list[tuple[int, int]]]:
    """Split a single oversized chunk into ``parts`` consecutive pieces.

    One LLM call over a whole 8-minute part tends to answer from the first
    half only: the model reads top-down and runs out of attention before it
    reaches the end. Splitting the range and allocating the quota across the
    pieces forces answers to be spread over the audio, which is what an
    IELTS paper looks like.
    """
    if parts <= 1 or len(chunks) != 1:
        return chunks
    flat = chunks[0]
    if len(flat) < parts:
        return chunks
    per = max(1, len(flat) // parts)
    out: list[list[tuple[int, int]]] = []
    for i in range(parts):
        start = i * per
        end = len(flat) if i == parts - 1 else (i + 1) * per
        piece = flat[start:end]
        if piece:
            out.append(piece)
    return out


def _allocate(total: int, sizes: list[int]) -> list[int]:
    """Largest-remainder allocation with at least one item per chunk."""
    n = len(sizes)
    if n == 0:
        return []
    if total <= n:
        return [1 if i < total else 0 for i in range(n)]
    weight = sum(sizes) or 1
    raw = [total * s / weight for s in sizes]
    base = [max(1, int(x)) for x in raw]
    while sum(base) > total:
        idx = max(range(n), key=lambda i: base[i])
        base[idx] -= 1
    remainders = sorted(
        range(n), key=lambda i: (raw[i] - int(raw[i])), reverse=True
    )
    i = 0
    while sum(base) < total:
        base[remainders[i % n]] += 1
        i += 1
    return base


def _build_messages(
    conn,
    words_json: list[dict],
    sentences: list[list[int]],
    *,
    part: int,
    qtype: QuestionType,
    ranges: list[tuple[int, int]],
    allowed: list[tuple[int, int]],
    count: int,
    lang: str,
    shared_options: list[str] | None = None,
    variation: int | None = None,
) -> list[dict]:
    """Three-part message list (design §8.1), ordered by prefix stability.

    system (globally stable) -> stable frame (per material: transcript +
    candidates, byte-identical across requests over the same material) ->
    task frame (per request: type rules, count, JSON schema hint). The
    texts are the Task 5 registry's verbatim migration of the legacy
    single user message; only the position of the segments changed.
    ``part`` is the block's 1-based ordinal in the request (the template
    header slot -- Part is no longer a product concept). ``variation``
    (regenerate=True) appends a fixed marker line to the task frame so
    the exact-match llm_cache key changes (design §8.3).
    """
    label = _type_name(qtype, lang)
    candidates = (
        _candidate_hint(words_json, sentences, allowed, count)
        if qtype.answer_kind == "span"
        else "（本题型不需要）" if lang == "zh" else "(not used for this type)"
    )
    rules = _rules_text(conn, qtype, lang)
    if shared_options:
        # One printed option list per task: a chunk must not invent a second
        # pool, because letters from a discarded pool make the key wrong.
        listed = "\n".join(shared_options)
        if lang == "zh":
            rules += (
                "\n本题必须原样使用下面这组选项（不要新增、删除或改写），"
                "answer 只能是其中一个字母：\n" + listed
            )
        else:
            rules += (
                "\nUse exactly this option list (do not add, drop or reword "
                "options); answer must be one of its letters:\n" + listed
            )
    task_frame = prompts.render_prompt(
        conn,
        "exam.task_frame",
        lang,
        part=part,
        label=label,
        count=count,
        instruction=_task_instruction(qtype),
        rules=rules,
        gap=MIN_GAP_WORDS,
        schema=_schema_hint(qtype),
    )
    if variation is not None:
        task_frame += f"\nvariation: {variation}"
    return [
        {
            "role": "system",
            "content": prompts.render_prompt(conn, "exam.system", lang),
        },
        {
            "role": "user",
            "content": prompts.render_prompt(
                conn,
                "exam.stable_frame",
                lang,
                transcript=_render_ranges(words_json, ranges),
                candidates=candidates,
            ),
        },
        {"role": "user", "content": task_frame},
    ]


async def _call_group(
    chat,
    conn,
    llm_cfg: Any,
    messages: list[dict],
    task: str,
    client=None,
) -> tuple[dict, Any, bool]:
    """One block-level cached call; normalizes injected-fake errors.

    ``chat`` follows the :func:`llm.cached_chat_json` contract:
    ``(conn, cfg, messages, *, task, ...) -> (obj, ChatUsage, from_cache)``.
    """
    try:
        return await chat(conn, llm_cfg, messages, task=task, client=client)
    except LlmError:
        raise
    except Exception as exc:  # network layer from an injected fake
        raise LlmError(str(exc)) from exc


async def _generate_block(
    conn,
    words_json: list[dict],
    sentences: list[list[int]],
    *,
    part: int,
    qtype: QuestionType,
    count: int,
    llm_cfg: Any,
    lang: str,
    ctx: ExamContext,
    zone: list[tuple[int, int]] | None = None,
    shared_options: list[str] | None = None,
    layout_hint: str | None = None,
    variation: int | None = None,
    client=None,
    chat_fn=None,
    usage: list[dict] | None = None,
) -> tuple[list[tuple[str, list[ExamItem], list[str]]], list[str]]:
    """Generate one request block (one type, N items) from an audio zone.

    ``zone`` is this block's slice of the audio (the blocks' user order is
    the zone order, design §4.4, so a MCQ block placed first reads the
    first zone exactly as the user arranged). ``shared_options`` makes every
    chunk -- and every later block of the same type -- reuse one option
    pool. ``layout_hint`` forces every completion item's layout (§4.1);
    ``variation`` (regenerate) appends the cache-busting marker (§8.3).
    Every LLM call is task-labelled ``exam:<type>`` and lands in ``usage``.
    """
    content = content_ranges(words_json, sentences)
    if not content:
        raise ExamGenError("转写中没有可命题的内容句（可能全是考试指令）")

    # The old pipeline's failure mode: blanking the opening/closing sentence.
    # Protect both edges of the *whole material* from answers; they remain
    # visible as context for option-based types. A middle zone needs no
    # extra guard.
    whole_allowed = content[1:-1] if len(content) >= 4 else content
    if not whole_allowed:
        whole_allowed = content
    if zone:
        content = zone
        allowed = [
            (s, e)
            for s, e in zone
            if any(a <= s and e <= b for a, b in whole_allowed)
        ] or zone
    else:
        allowed = whole_allowed

    chat = chat_fn or llm.cached_chat_json
    task = f"exam:{qtype.key}"
    if usage is None:
        usage = []

    async def call(messages: list[dict]) -> Mapping:
        obj, call_usage, from_cache = await _call_group(
            chat, conn, llm_cfg, messages, task, client
        )
        usage.append(
            {
                "task": task,
                "prompt_tokens": call_usage.prompt_tokens,
                "completion_tokens": call_usage.completion_tokens,
                "cached_tokens": call_usage.cached_tokens,
                "cached_hit": from_cache,
            }
        )
        return obj

    chunks = _pack_ranges(content)
    # Spread a single-pass completion block across the audio instead of letting
    # one call answer from the opening minutes only.
    #
    # Matching is deliberately NOT chunked: each chunk would return its own
    # option list, and two lists for one task silently break the answer key
    # (a letter means something different in each pool). One call = one pool.
    if len(chunks) == 1 and count >= 4 and qtype.answer_kind != "matching":
        chunks = _split_for_coverage(chunks, 3 if count >= 9 else 2)
    sizes = [sum(e - s + 1 for s, e in chunk) for chunk in chunks]
    counts = _allocate(count, sizes)

    results: list[tuple[str, list[ExamItem], list[str]]] = []
    warnings: list[str] = []
    seen: set[tuple[int, int]] = set()
    seen_answers: set[str] = set()

    def accept(blocks) -> int:
        added = 0
        for title, items, options, errs in blocks:
            kept: list[ExamItem] = []
            for item in items:
                # The per-group limit in _validate_response does not cap the
                # *block*: a retry that returns two groups could overshoot.
                if sum(len(g) for _t, g, _o in results) + len(kept) >= count:
                    break
                # Completion answers live on a unique span; option and matching
                # items may legitimately share the sentence that supports them.
                span_key = (
                    (item.evidence[0].i0, item.evidence[0].i1)
                    if item.evidence and qtype.answer_kind == "span"
                    else None
                )
                answer_key = _norm(item.answer) if qtype.answer_kind == "span" else ""
                if span_key is not None and span_key in seen:
                    warnings.append(f"拒绝：与已选题目重复（{item.answer}）")
                    continue
                if answer_key and answer_key in seen_answers:
                    warnings.append(f"拒绝：答案重复（{item.answer}）")
                    continue
                if answer_key:
                    nested = _nested_answer(item.answer, list(seen_answers))
                    if nested:
                        warnings.append(
                            f"拒绝：答案 {item.answer!r} 与已选 {nested!r} 重复考查同一信息"
                        )
                        continue
                if span_key is not None:
                    seen.add(span_key)
                if answer_key:
                    seen_answers.add(answer_key)
                kept.append(item)
            warnings.extend(errs)
            if kept:
                results.append((title, kept, options))
                added += len(kept)
        return added

    local_pool = list(shared_options) if shared_options else None
    for ci, chunk in enumerate(chunks):
        quota = counts[ci]
        if quota <= 0:
            continue
        chunk_allowed = [
            (s, e)
            for s, e in allowed
            if any(a <= s <= b for a, b in chunk)
        ]
        if not chunk_allowed:
            chunk_allowed = chunk
        user_messages = _build_messages(
            conn,
            words_json,
            sentences,
            part=part,
            qtype=qtype,
            ranges=chunk,
            allowed=chunk_allowed,
            count=quota,
            lang=lang,
            shared_options=local_pool,
            variation=variation,
        )
        try:
            obj = await call(user_messages)
        except LlmError as exc:
            warnings.append(f"{qtype.key} 第 {ci + 1} 段 LLM 调用失败：{exc}")
            continue

        blocks = _validate_response(
            obj,
            words_json,
            sentences,
            qtype,
            chunk_allowed,
            quota,
            ctx,
            shared_options=local_pool,
            layout_hint=layout_hint,
        )
        if local_pool is None and qtype.answer_kind == "matching":
            for _t, _items, chunk_options, _errs in blocks:
                if chunk_options:
                    local_pool = list(chunk_options)
                    break
        accept(blocks)

    # One repair round for a short single-chunk run. It fires whenever the
    # block is short -- not only after a rejection: the model sometimes just
    # returns fewer items than asked for, with nothing to quote back at it.
    total_valid = sum(len(items) for _t, items, _o in results)
    if total_valid < count:
        missing = count - total_valid
        rejected = [w for w in warnings if w.startswith("拒绝")]
        # The repair suffix rides on the tail of the task frame (the least
        # stable message), leaving the system + stable-frame prefix intact.
        retry_messages = _build_messages(
            conn,
            words_json,
            sentences,
            part=part,
            qtype=qtype,
            ranges=content,
            allowed=allowed,
            count=missing,
            lang=lang,
            variation=variation,
        )
        retry_messages[-1] = {
            **retry_messages[-1],
            "content": retry_messages[-1]["content"]
            + (
                "\n\n上一轮以下题目未通过校验：\n"
                + "\n".join(f"- {r}" for r in rejected[:12])
                + "\n"
                if rejected
                else "\n\n上一轮题量不足。\n"
            )
            + f"请再生成 {missing} 道，避开上述问题；"
            "不要重复上一轮已经通过的答案。",
        }
        try:
            obj = await call(retry_messages)
            accept(
                _validate_response(
                    obj,
                    words_json,
                    sentences,
                    qtype,
                    allowed,
                    missing,
                    ctx,
                    shared_options=local_pool,
                    layout_hint=layout_hint,
                )
            )
        except LlmError:
            pass

    # Deterministic top-up: a paper must come back with the advertised count.
    total_valid = sum(len(items) for _t, items, _o in results)
    if total_valid < count and qtype.answer_kind == "span":
        existing = [it for _t, items, _o in results for it in items]
        filler = _top_up_from_candidates(
            words_json,
            sentences,
            qtype,
            allowed,
            ctx,
            existing,
            count - total_valid,
            layout_hint=layout_hint,
        )
        if filler:
            results.append(("", filler, []))
            warnings.append(f"规则补题 {len(filler)} 道（LLM 未凑满）")

    return _merge_span_groups(results, qtype), warnings


def _stem_for(
    words_json: list[dict],
    sentences: list[list[int]],
    i0: int,
    i1: int,
) -> str:
    """Build a completion stem from the owning sentence with the span blanked."""
    words = [str(w.get("w", "")) for w in words_json]
    owner = next(
        ((s, e) for s, e in normalize_ranges(len(words), sentences) if s <= i0 <= e),
        (i0, i1),
    )
    start, end = owner[0], max(owner[1], i1)
    # One blank marker per answer span, even when the answer is two words:
    # IELTS prints a single gap and the answer fills it.
    return " ".join(
        ["______" if i == i0 else words[i] for i in range(start, i0)]
        + ["______"]
        + [words[i] for i in range(i1 + 1, end + 1)]
    )


def _top_up_from_candidates(
    words_json: list[dict],
    sentences: list[list[int]],
    qtype: QuestionType,
    allowed: list[tuple[int, int]],
    ctx: ExamContext,
    have: list[ExamItem],
    need: int,
    layout_hint: str | None = None,
) -> list[ExamItem]:
    """Deterministically fill a shortfall from the POS candidate pool.

    The LLM is preferred, but a paper must not silently come back short:
    matching IELTS delivery needs exactly the advertised item count. Each
    filler item carries a word_limit fitted to its own answer's actual
    word count (§4.1; a number phrase counts as one word) and the same
    layout rules as LLM items.
    """
    if need <= 0 or qtype.answer_kind != "span":
        return []
    try:
        # A small request returns only the highest-scoring spans, which are
        # mostly 2-3 word phrases; a strict ONE WORD ONLY type would then see
        # nothing usable. Ask for a pool large enough to contain single words.
        pool = pos.build_candidates(words_json, sentences, max(need * 40, 80))
    except Exception:
        return []

    taken_spans = [(it.evidence[0].i0, it.evidence[0].i1) for it in have if it.evidence]
    taken_answers = [it.answer for it in have]
    picked: list[ExamItem] = []

    for cand in pool:
        if len(picked) >= need:
            break
        i0 = int(cand["i0"])
        i1 = int(cand.get("i1", i0))
        if not (_covered(i0, allowed) and _covered(i1, allowed)):
            continue
        if _unfair_name_answer(ctx, i0, i1):
            continue
        counted = 1 if _counts_as_number(words_json, i0, i1) else i1 - i0 + 1
        if i1 - i0 + 1 > MAX_SPAN_WORDS:
            continue
        if any(s <= i1 and i0 <= e for s, e in taken_spans):
            continue
        answer = _answer_text(words_json, i0, i1)
        if not answer:
            continue
        if _nested_answer(answer, taken_answers):
            continue
        # The 5-word gap is a paper-design rule: keep it between every pair.
        if any(
            not (e + MIN_GAP_WORDS < i0 or i1 + MIN_GAP_WORDS < s)
            for s, e in taken_spans
        ):
            continue
        stem = _stem_for(words_json, sentences, i0, i1)
        if not _BLANK_RE.search(stem):
            continue
        if _norm(answer) in _norm(_BLANK_RE.sub(" ", stem)):
            continue
        if qtype.key == "short_answer":
            word_limit = SHORT_ANSWER_WORD_LIMIT
        else:
            word_limit = _limit_for_words(counted)
        picked.append(
            ExamItem(
                number=0,
                type_key=qtype.key,
                stem=stem,
                answer=answer,
                evidence=[
                    Evidence(
                        i0=i0,
                        i1=i1,
                        quote=_span_text(words_json, i0, i1),
                        t_start=float(words_json[i0].get("s", 0.0) or 0.0),
                        t_end=float(words_json[i1].get("e", 0.0) or 0.0),
                    )
                ],
                word_limit=word_limit,
                layout=(layout_hint or DEFAULT_LAYOUT) if qtype.layouts else None,
                label=str(cand.get("type", "")),
                alternatives=list(cand.get("alternatives") or []),
            )
        )
        taken_spans.append((i0, i1))
        taken_answers.append(answer)
    return picked


def _letter_pool(options: list[str]) -> list[str]:
    """Return options with an explicit ``A.``-style prefix on every entry.

    The LLM sometimes returns a bare list ("to inform the public", ...) and
    still keys answers as D/E/F by list position. Printing that raw list
    leaves no letters to choose from, so the paper must be normalized.
    """
    letters = "ABCDEFGH"
    out: list[str] = []
    for i, opt in enumerate(options):
        text = opt.strip()
        if text[:1].upper() in letters and text[1:2] in (".", ")", " ", ""):
            out.append(text)
        else:
            out.append(f"{letters[i]}. {text}" if i < len(letters) else text)
    return out


def _pool_key(options: list[str]) -> tuple[str, ...]:
    return tuple(_norm(re.sub(r"^[A-H][.)]\s*", "", o)) for o in options)


def _merge_span_groups(
    blocks: list[tuple[str, list[ExamItem], list[str]]],
    qtype: QuestionType,
) -> list[tuple[str, list[ExamItem], list[str]]]:
    """Merge chunked calls into the paper's natural blocks.

    Completion types: one form/note/table is one numbered list, no matter how
    many chunks produced it. Matching: blocks sharing an identical option pool
    merge into one task; blocks with a different pool stay separate tasks,
    because a letter means something different in each pool (the audit found
    items keyed against a discarded second pool).
    """
    if len(blocks) <= 1:
        return blocks
    if qtype.answer_kind == "span":
        items = [it for _t, group_items, _o in blocks for it in group_items]
        items.sort(key=lambda it: (it.evidence[0].i0, it.evidence[0].i1) if it.evidence else (0, 0))
        title = next((t for t, _i, _o in blocks if t), "")
        return [(title, items, [])]
    if qtype.answer_kind in ("option", "option_multi"):
        # A 5-item MCQ task prints as one numbered block, not one block per
        # chunk. Items were validated per chunk; keep audio order.
        items = [it for _t, group_items, _o in blocks for it in group_items]
        items.sort(key=lambda it: (it.evidence[0].i0, it.evidence[0].i1) if it.evidence else (0, 0))
        return [("", items, [])]
    if qtype.answer_kind != "matching":
        return blocks

    merged: list[tuple[str, list[ExamItem], list[str]]] = []
    by_pool: dict[tuple[str, ...], int] = {}
    for title, group_items, group_options in blocks:
        key = _pool_key(group_options)
        if group_options and key in by_pool:
            idx = by_pool[key]
            m_title, m_items, m_options = merged[idx]
            merged[idx] = (m_title, m_items + group_items, m_options)
        else:
            if group_options:
                by_pool[key] = len(merged)
            merged.append((title, list(group_items), list(group_options)))

    out: list[tuple[str, list[ExamItem], list[str]]] = []
    for title, group_items, group_options in merged:
        # Option uniqueness is per task: two items keyed to the same letter in
        # one pool would be ambiguous on the printed paper.
        used: set[str] = set()
        kept: list[ExamItem] = []
        for item in group_items:
            if item.answer in used:
                continue
            used.add(item.answer)
            kept.append(item)
        if kept:
            out.append((title, kept, group_options))
    return out


def _validate_response(
    obj: Mapping,
    words_json: list[dict],
    sentences: list[list[int]],
    qtype: QuestionType,
    allowed: list[tuple[int, int]],
    limit: int,
    ctx: ExamContext,
    shared_options: list[str] | None = None,
    layout_hint: str | None = None,
) -> list[tuple[str, list[ExamItem], list[str], list[str]]]:
    """Validate one LLM response; returns ``[(title, items, options, warnings)]``."""
    groups = obj.get("groups")
    if not isinstance(groups, list):
        return [("", [], [], ["拒绝：LLM 未返回 groups 数组"])]
    out: list[tuple[str, list[ExamItem], list[str], list[str]]] = []
    lo, hi = _options_range(qtype)
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        title = str(group.get("title") or "")
        group_layout = str(group.get("layout") or "").strip().lower()
        raw_items = group.get("items")
        if not isinstance(raw_items, list):
            continue
        warnings: list[str] = []
        items: list[ExamItem] = []
        options: list[str] = []

        if qtype.answer_kind == "matching":
            # A matching task prints ONE option list. When the block already
            # has a pool, force it: a chunk that invents its own pool would
            # renumber the letters and silently break the answer key.
            if shared_options:
                options = list(shared_options)
            else:
                options = [
                    str(o).strip()
                    for o in (group.get("options") or [])
                    if str(o).strip()
                ]
            if not (lo <= len(options) <= hi):
                warnings.append(
                    f"拒绝：匹配选项数 {len(options)} 超出 " f"{lo}-{hi}"
                )
                out.append((title, [], options, warnings))
                continue
            if len({_norm(o) for o in options}) != len(options):
                warnings.append("拒绝：匹配选项重复")
                out.append((title, [], options, warnings))
                continue
            used: set[str] = set()
            for raw in raw_items:
                if not isinstance(raw, Mapping):
                    continue
                item, err = _validate_matching_item(
                    raw, options, words_json, sentences, qtype
                )
                if err:
                    warnings.append(f"拒绝：{err}")
                    continue
                assert item is not None
                if item.answer in used:
                    warnings.append(f"拒绝：选项 {item.answer} 被重复匹配")
                    continue
                used.add(item.answer)
                item.group_title = title
                items.append(item)
        elif qtype.answer_kind in ("option", "option_multi"):
            for raw in raw_items:
                if not isinstance(raw, Mapping):
                    continue
                item, err = _validate_option_item(
                    raw, words_json, sentences, qtype
                )
                if err:
                    warnings.append(f"拒绝：{err}")
                    continue
                assert item is not None
                item.group_title = title
                items.append(item)
        else:
            for raw in raw_items:
                if not isinstance(raw, Mapping):
                    continue
                item, err = _validate_completion(
                    raw, words_json, sentences, qtype, allowed, ctx,
                    group_layout=group_layout, layout_hint=layout_hint,
                )
                if err:
                    warnings.append(f"拒绝：{err}")
                    continue
                assert item is not None
                item.group_title = title
                items.append(item)

        if qtype.answer_kind == "span":
            items, gap_warnings = _enforce_gap(items, limit)
            warnings.extend(gap_warnings)
        else:
            items = sorted(
                items,
                key=lambda it: (
                    it.evidence[0].i0 if it.evidence else 0,
                    it.evidence[0].i1 if it.evidence else 0,
                ),
            )
            items = items[:limit]
        out.append((title, items, options, warnings))
    return out


def _paper_count(conn, material_id: str) -> int:
    """Existing persisted papers for this material (regenerate marker).

    The ``papers`` table lands with persistence (Task 14); until then (or
    for ad-hoc connections without it) the count is zero, so the first
    regenerate marker is ``variation: 1``.
    """
    if conn is None or not material_id:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM papers WHERE material_id=?",
            (material_id,),
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row is not None else 0


def _material_words(material: Mapping) -> list[dict]:
    raw = material.get("words_json") or []
    if isinstance(raw, str):
        raw = json.loads(raw or "[]")
    return [w for w in raw if isinstance(w, dict)] if isinstance(raw, list) else []


def _material_sentences(material: Mapping) -> list[list[int]]:
    raw = material.get("sentences_json") or []
    if isinstance(raw, str):
        raw = json.loads(raw or "[]")
    return raw if isinstance(raw, list) else []


def _parse_blocks(blocks) -> list[tuple[QuestionType, int]]:
    """Validate ``[{type, count}]`` against the registry (design §4.4)."""
    if not isinstance(blocks, list) or not blocks:
        raise ExamGenError("blocks 不能为空：至少需要一个 {type, count} 块")
    specs: list[tuple[QuestionType, int]] = []
    for raw in blocks:
        if not isinstance(raw, Mapping):
            raise ExamGenError(f"block 不是对象：{raw!r}")
        qtype = QUESTION_TYPES.get(str(raw.get("type") or ""))
        if qtype is None:
            known = ", ".join(sorted(QUESTION_TYPES))
            raise ExamGenError(
                f"未知题型 {raw.get('type')!r}；可用题型：{known}"
            )
        count = raw.get("count")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not (1 <= count <= qtype.max_count)
        ):
            raise ExamGenError(
                f"题型 {qtype.key} 的题数必须是 1 到 {qtype.max_count} 的整数"
            )
        specs.append((qtype, count))
    return specs


async def generate_paper(
    conn,
    material: Mapping,
    blocks: list[dict],
    cfg: Any,
    *,
    lang: str = "zh",
    layout_hint: str | None = None,
    regenerate: bool = False,
    client=None,
    chat_fn=None,
) -> GenerateResult:
    """Generate one paper from ``blocks=[{type, count}]`` in user order.

    The block order is the audio zone order (design §4.4): each block is
    generated from its own consecutive slice of the content, in the order
    the user arranged them. Matching blocks never split their option pool;
    the whole paper is renumbered by earliest evidence. ``layout_hint``
    forces every completion item's layout (§4.1). ``regenerate=True``
    appends ``variation: <paper count + 1>`` to every task frame so the
    exact-match ``llm_cache`` key changes and the call produces fresh
    items (§8.3). ``chat_fn`` is the test seam for
    :func:`llm.cached_chat_json`.
    """
    material_id = str(material.get("id") or "")
    words_json = _material_words(material)
    sentences = _material_sentences(material)
    if not words_json:
        raise ExamGenError("材料没有词表，无法出题")
    if cfg is None:
        raise ExamGenError("未配置 LLM，无法生成完整题型")
    specs = _parse_blocks(blocks)
    if layout_hint is not None and layout_hint not in (
        QUESTION_TYPES["completion"].layouts
    ):
        raise ExamGenError(
            f"未知 layout {layout_hint!r}；可用："
            + ", ".join(QUESTION_TYPES["completion"].layouts)
        )

    variation = _paper_count(conn, material_id) + 1 if regenerate else None

    paper = ExamPaper(material_id=material_id)
    usage: list[dict] = []
    skipped: list[dict] = []
    ctx = build_context(words_json, sentences)

    # Deterministic prechecks (design §4.5), no LLM call spent:
    #   * visual types wait for the scene path (§4.3, later task);
    #   * a transcript under the type's min_words floor cannot feed it.
    active: list[tuple[QuestionType, int]] = []
    for qtype, count in specs:
        if qtype.generates_visual:
            paper.warnings.append(
                f"{_type_name(qtype, lang)}需要场景还原"
                f"（地图场景随后续任务开放），本次已跳过"
            )
            continue
        if len(words_json) < qtype.min_words:
            paper.warnings.append(
                f"{_type_name(qtype, lang)}需要至少 {qtype.min_words} 词的转写"
                f"（当前 {len(words_json)} 词），本次已跳过"
            )
            continue
        active.append((qtype, count))
    if not active:
        raise ExamGenError(
            "没有可生成的题型块：" + "；".join(paper.warnings)
        )

    content = content_ranges(words_json, sentences)
    if not content:
        raise ExamGenError("转写中没有可命题的内容句（可能全是考试指令）")

    # Zone the audio in block order: block 1 reads the first slice, block 2
    # the second, and so on -- a two-block paper looks like a real paper's
    # task change instead of two blocks interleaving over the same audio.
    zones: list[list[tuple[int, int]] | None]
    if len(active) > 1:
        per = max(1, len(content) // len(active))
        zones = []
        for i in range(len(active)):
            start = i * per
            end = len(content) if i == len(active) - 1 else (i + 1) * per
            zones.append(content[start:end] or content[-1:])
    else:
        zones = [None]

    shared_pool_by_type: dict[str, list[str]] = {}
    for ordinal, ((qtype, count), zone) in enumerate(zip(active, zones), start=1):
        shared = (
            shared_pool_by_type.get(qtype.key)
            if qtype.answer_kind == "matching"
            else None
        )
        try:
            blocks_out, block_warnings = await _generate_block(
                conn,
                words_json,
                sentences,
                part=ordinal,
                qtype=qtype,
                count=count,
                llm_cfg=cfg,
                lang=lang,
                ctx=ctx,
                zone=zone,
                shared_options=shared,
                layout_hint=layout_hint,
                variation=variation,
                client=client,
                chat_fn=chat_fn,
                usage=usage,
            )
        except ExamGenError as exc:
            paper.warnings.append(str(exc))
            continue
        paper.warnings.extend(block_warnings)

        if qtype.answer_kind == "matching" and qtype.key not in shared_pool_by_type:
            for _t, _items, options in blocks_out:
                if options:
                    shared_pool_by_type[qtype.key] = list(options)
                    break

        for title, items, options in blocks_out:
            if not items:
                continue
            paper.groups.append(
                ExamGroup(
                    type_key=qtype.key,
                    title=title or _type_name(qtype, lang),
                    instruction=_group_instruction(qtype, items),
                    items=items,
                    options=_letter_pool(options) if options else [],
                )
            )

    # Number the whole paper in audio order. Blocks are zoned so their items
    # follow the block order, but if a block's items are heard earlier they
    # must print earlier too -- otherwise the numbering contradicts the audio.
    def earliest(group: ExamGroup) -> int:
        times = [it.evidence[0].i0 for it in group.items if it.evidence]
        return min(times) if times else 1 << 30

    paper.groups.sort(key=earliest)
    number = 1
    for item in (it for group in paper.groups for it in group.items):
        item.number = number
        number += 1

    if paper.total_items == 0:
        raise ExamGenError(
            "没有生成任何可用题目；请检查转写内容或 LLM 返回"
        )
    return GenerateResult(paper=paper.to_dict(), skipped=skipped, usage=usage)
