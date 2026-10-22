"""Question-type registry for the paper generator (redesign §4).

Six types, keyed by what the candidate does -- choose letters, match a
shared option pool, or write down a transcript span. ``Part`` is no
longer an input: a type can appear anywhere the user puts it, so the
part-based paper presets are gone (the frontend ships its own
"recommended combination" shortcuts; the backend takes free ``blocks``).

``completion`` absorbs the six legacy fill-in types (form / table /
notes / sentence / summary / flow-chart). Those names survive only as
``layouts`` -- a per-item presentation choice suggested by the LLM from
the content's shape, not separate types with separate code paths.

The registry is data, not code: adding a question type must not require
editing the generator. Pure stdlib and framework-free, like the rest of
``app.services``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionType:
    """One question type.

    ``answer_kind`` drives the LLM schema and the validator:
      - ``span``: the answer is a verbatim transcript span
        (completion, short_answer)
      - ``option``: the answer is one option letter (mcq_single)
      - ``option_multi``: the answer is several option letters, "A,C"
        (mcq_multi)
      - ``matching``: the answer is one letter from a shared option pool
        (matching, map_labelling)

    ``min_words`` is the deterministic precheck floor (design §4.5): a
    transcript under this word count is refused for the type before any
    LLM call is spent. ``max_count`` caps how many items one block of
    this type may request. ``generates_visual`` marks types that produce
    a scene asset the frontend renders (map_labelling).
    """

    key: str
    answer_kind: str
    name_zh: str
    name_en: str
    min_words: int
    # Presentation layouts; completion only, empty for the other types.
    layouts: tuple[str, ...] = ()
    generates_visual: bool = False
    max_count: int = 10


QUESTION_TYPES: dict[str, QuestionType] = {
    "mcq_single": QuestionType(
        key="mcq_single",
        answer_kind="option",
        name_zh="单选题",
        name_en="Multiple choice (single answer)",
        min_words=120,
    ),
    "mcq_multi": QuestionType(
        key="mcq_multi",
        answer_kind="option_multi",
        name_zh="多选题（选两项）",
        name_en="Multiple choice (two answers)",
        min_words=200,
    ),
    "matching": QuestionType(
        key="matching",
        answer_kind="matching",
        name_zh="匹配题",
        name_en="Matching",
        min_words=150,
    ),
    "completion": QuestionType(
        key="completion",
        answer_kind="span",
        name_zh="填空题",
        name_en="Completion",
        min_words=80,
        layouts=("form", "table", "notes", "sentence", "summary", "flowchart"),
    ),
    "short_answer": QuestionType(
        key="short_answer",
        answer_kind="span",
        name_zh="简答题",
        name_en="Short answer",
        min_words=80,
    ),
    "map_labelling": QuestionType(
        key="map_labelling",
        answer_kind="matching",
        name_zh="地图标注",
        name_en="Map labelling",
        min_words=200,
        generates_visual=True,
    ),
}
