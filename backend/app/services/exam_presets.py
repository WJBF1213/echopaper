"""Preset registry for the full IELTS Listening paper generator (experiment).

The registry is data, not code. Adding a question type or a paper blueprint
must not require editing the generator: a preset declares which IELTS parts
it can appear in, the answer shape, the paper instruction, the prompt rules,
and whether it needs a visual asset (map / plan / diagram) that audio alone
cannot supply.

Pure stdlib and framework-free, like the rest of ``app.services``.
"""
from __future__ import annotations

from dataclasses import dataclass


def localized(value: dict[str, str], lang: str = "zh") -> str:
    """Pick a localized string, falling back to Chinese then the first entry."""
    return value.get(lang) or value.get("zh") or next(iter(value.values()), "")


@dataclass(frozen=True)
class QuestionType:
    """One IELTS Listening question type.

    ``answer_kind`` drives the LLM schema and validator:
      - ``span``: answer is a verbatim transcript span (completion types)
      - ``option``: answer is an option letter (multiple choice)
      - ``option_multi``: answer is several option letters ("A,C")
      - ``matching``: answer is one option letter from a shared option list
    """

    key: str
    label: dict[str, str]
    parts: tuple[int, ...]
    answer_kind: str
    instruction: str
    rules_zh: str
    rules_en: str
    min_items: int = 3
    max_items: int = 10
    word_limit: str | None = None
    # Hard cap implied by ``word_limit`` (IELTS counts a number as one word).
    max_words: int = 3
    needs_visual: bool = False
    options_min: int = 0
    options_max: int = 0
    multi_count: int = 1

    @property
    def is_visual(self) -> bool:
        return self.needs_visual

    def rules(self, lang: str = "zh") -> str:
        template = self.rules_zh if lang == "zh" else self.rules_en
        try:
            return template.format(
                max_words=self.max_words, word_limit=self.word_limit or ""
            )
        except (KeyError, IndexError):
            return template


_COMPLETION_RULES_ZH = (
    "答案必须是给定转写中逐字连续的一段，且不超过 {max_words} 个词"
    "（数字整体算一个词：250、two hundred and fifty 均算一个）。"
    "不得改写、翻译或补全。"
    "stem 用英文原句，把答案位置替换为 ______；form/note 可另给 label。"
    "不要考句首两词、考试指令、问候与告别语。"
)
_COMPLETION_RULES_EN = (
    "The answer must be a verbatim, contiguous span from the transcript of "
    "at most {max_words} word(s), where a whole number counts as one word "
    "(250 and 'two hundred and fifty' both count as one). Never paraphrase, "
    "translate or complete it. Write the stem as the original English "
    "sentence with the answer replaced by ______; form/note items may add a "
    "label. Never test the first two words of a sentence, exam rubrics, "
    "greetings or sign-offs."
)

QUESTION_TYPES: dict[str, QuestionType] = {
    "form_completion": QuestionType(
        key="form_completion",
        label={"zh": "表单填空", "en": "Form completion"},
        parts=(1,),
        answer_kind="span",
        instruction=(
            "Complete the form below. Write NO MORE THAN TWO WORDS "
            "AND/OR A NUMBER for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH + "表单题要给出字段标签 label（如 Name、Deposit）。",
        rules_en=_COMPLETION_RULES_EN
        + " Form items must include a short field label (Name, Deposit, ...).",
        word_limit="NO MORE THAN TWO WORDS AND/OR A NUMBER",
        max_words=2,
    ),
    "note_completion": QuestionType(
        key="note_completion",
        label={"zh": "笔记填空", "en": "Note completion"},
        parts=(2, 4),
        answer_kind="span",
        instruction=(
            "Complete the notes below. Write ONE WORD ONLY for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH + "按主题分组（每组 2-4 题），组标题用英文。",
        rules_en=_COMPLETION_RULES_EN
        + " Group items by topic (2-4 per group) with an English group title.",
        word_limit="ONE WORD ONLY",
        max_words=1,
    ),
    "table_completion": QuestionType(
        key="table_completion",
        label={"zh": "表格填空", "en": "Table completion"},
        parts=(2, 4),
        answer_kind="span",
        instruction=(
            "Complete the table below. Write ONE WORD AND/OR A NUMBER "
            "for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH + "每题的 label 写所在行/列的提示词。",
        rules_en=_COMPLETION_RULES_EN
        + " Each item's label should name its row or column cue.",
        word_limit="ONE WORD AND/OR A NUMBER",
        max_words=1,
    ),
    "sentence_completion": QuestionType(
        key="sentence_completion",
        label={"zh": "句子填空", "en": "Sentence completion"},
        parts=(2, 3, 4),
        answer_kind="span",
        instruction=(
            "Complete the sentences below. Write NO MORE THAN TWO WORDS "
            "for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH + "题干必须是原文中的完整句子。",
        rules_en=_COMPLETION_RULES_EN
        + " The stem must be a complete sentence taken from the transcript.",
        word_limit="NO MORE THAN TWO WORDS",
        max_words=2,
    ),
    "summary_completion": QuestionType(
        key="summary_completion",
        label={"zh": "摘要填空", "en": "Summary completion"},
        parts=(3, 4),
        answer_kind="span",
        instruction=(
            "Complete the summary below. Write NO MORE THAN TWO WORDS "
            "for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH
        + "摘要可用同义改写，但每个答案仍须是原文逐字跨度；不要连续挖相邻词。",
        rules_en=_COMPLETION_RULES_EN
        + " The summary may paraphrase, but each answer stays verbatim and "
        "two blanks must never be adjacent.",
        word_limit="NO MORE THAN TWO WORDS",
        max_words=2,
    ),
    "flowchart_completion": QuestionType(
        key="flowchart_completion",
        label={"zh": "流程图填空", "en": "Flow-chart completion"},
        parts=(2, 3),
        answer_kind="span",
        instruction=(
            "Complete the flow-chart below. Write ONE WORD ONLY "
            "for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH + "按流程顺序出题，每题 label 写流程步骤名。",
        rules_en=_COMPLETION_RULES_EN
        + " Follow the process order; each label names its step.",
        word_limit="ONE WORD ONLY",
        max_words=1,
    ),
    "short_answer": QuestionType(
        key="short_answer",
        label={"zh": "简答题", "en": "Short answer"},
        parts=(1, 2, 3),
        answer_kind="span",
        instruction=(
            "Answer the questions below. Write NO MORE THAN THREE WORDS "
            "for each answer."
        ),
        rules_zh=_COMPLETION_RULES_ZH
        + "题干写成英文疑问句，答案必须是原文中能直接回答该问题的词跨度。",
        rules_en=_COMPLETION_RULES_EN
        + " Write an English question; the answer span must directly answer it.",
        word_limit="NO MORE THAN THREE WORDS",
        max_words=3,
    ),
    "mcq_single": QuestionType(
        key="mcq_single",
        label={"zh": "单选题", "en": "Multiple choice (single answer)"},
        parts=(2, 3),
        answer_kind="option",
        instruction="Choose the correct letter, A, B or C.",
        rules_zh=(
            "每题 3 个选项、恰好 1 个正确。正确项必须由原文明确支持；"
            "干扰项必须与原文矛盾或原文未提及，不能同样成立。"
            "evidence 引用支持正确答案的原文词跨度；题干用英文。"
        ),
        rules_en=(
            "Exactly 3 options and 1 correct answer. The correct option must "
            "be explicitly supported by the transcript; distractors must be "
            "contradicted or unsupported, never also true. Cite the supporting "
            "span as evidence. Write the stem in English."
        ),
        options_min=3,
        options_max=3,
    ),
    "mcq_multi": QuestionType(
        key="mcq_multi",
        label={"zh": "多选题（选两项）", "en": "Multiple choice (two answers)"},
        parts=(3,),
        answer_kind="option_multi",
        instruction="Choose TWO letters, A-E.",
        rules_zh=(
            "每题 5 个选项、恰好 2 个正确。两个正确项都必须由原文支持；"
            "干扰项不得成立。answer 写成 \"A,C\"；evidence 引用支持两个正确项的词跨度。"
        ),
        rules_en=(
            "Exactly 5 options and 2 correct answers. Both must be supported "
            "by the transcript; distractors must not be true. Return answer "
            'as "A,C" and cite spans supporting both.'
        ),
        options_min=5,
        options_max=5,
        multi_count=2,
    ),
    "matching": QuestionType(
        key="matching",
        label={"zh": "匹配题", "en": "Matching"},
        parts=(2, 3),
        answer_kind="matching",
        instruction="Match each item with the correct option, A-F.",
        rules_zh=(
            "先给出 4-6 个选项组成的选项池 options，再出 3-6 道匹配题。"
            "每个选项最多使用一次，答案必须由原文明确支持；"
            "evidence 引用支持该匹配的词跨度。"
        ),
        rules_en=(
            "Provide a shared option list of 4-6 options, then 3-6 matching "
            "items. Each option is used at most once; every match must be "
            "explicitly supported by the transcript."
        ),
        options_min=4,
        options_max=6,
    ),
    "map_labelling": QuestionType(
        key="map_labelling",
        label={"zh": "地图标注", "en": "Map labelling"},
        parts=(1, 2),
        answer_kind="matching",
        instruction="Label the map below. Write the correct letter, A-F.",
        rules_zh="地图题需要一张地图图像；纯音频无法生成，必须由用户提供底图。",
        rules_en=(
            "Map labelling needs a map image; audio alone cannot generate it. "
            "The user must supply the base map."
        ),
        needs_visual=True,
        options_min=4,
        options_max=6,
    ),
    "plan_labelling": QuestionType(
        key="plan_labelling",
        label={"zh": "平面图标注", "en": "Plan labelling"},
        parts=(1, 2),
        answer_kind="matching",
        instruction="Label the plan below. Write the correct letter, A-F.",
        rules_zh="平面图题需要一张平面图；纯音频无法生成，必须由用户提供底图。",
        rules_en=(
            "Plan labelling needs a plan image; audio alone cannot generate "
            "it. The user must supply the base plan."
        ),
        needs_visual=True,
        options_min=4,
        options_max=6,
    ),
    "diagram_labelling": QuestionType(
        key="diagram_labelling",
        label={"zh": "示意图标注", "en": "Diagram labelling"},
        parts=(2, 3),
        answer_kind="matching",
        instruction="Label the diagram below. Write the correct letter, A-F.",
        rules_zh="示意图题需要一张示意图；纯音频无法生成，必须由用户提供底图。",
        rules_en=(
            "Diagram labelling needs a diagram image; audio alone cannot "
            "generate it. The user must supply the base diagram."
        ),
        needs_visual=True,
        options_min=4,
        options_max=6,
    ),
}


@dataclass(frozen=True)
class GroupSpec:
    """One question block inside a paper preset."""

    type_key: str
    count: int


@dataclass(frozen=True)
class PaperPreset:
    key: str
    part: int
    label: dict[str, str]
    groups: tuple[GroupSpec, ...]

    @property
    def total_items(self) -> int:
        return sum(g.count for g in self.groups)


PRESETS: dict[str, PaperPreset] = {
    "p1_form": PaperPreset(
        key="p1_form",
        part=1,
        label={"zh": "Part 1 · 表单填空（10 题）", "en": "Part 1 · Form completion (10)"},
        groups=(GroupSpec("form_completion", 10),),
    ),
    "p1_short": PaperPreset(
        key="p1_short",
        part=1,
        label={"zh": "Part 1 · 简答题（10 题）", "en": "Part 1 · Short answer (10)"},
        groups=(GroupSpec("short_answer", 10),),
    ),
    "p2_mcq_matching": PaperPreset(
        key="p2_mcq_matching",
        part=2,
        label={
            "zh": "Part 2 · 单选 + 匹配（5+5）",
            "en": "Part 2 · Multiple choice + matching (5+5)",
        },
        groups=(GroupSpec("mcq_single", 5), GroupSpec("matching", 5)),
    ),
    "p2_map_mcq": PaperPreset(
        key="p2_map_mcq",
        part=2,
        label={
            "zh": "Part 2 · 地图 + 单选（5+5，需底图）",
            "en": "Part 2 · Map + multiple choice (5+5, needs a map)",
        },
        groups=(GroupSpec("map_labelling", 5), GroupSpec("mcq_single", 5)),
    ),
    "p3_mcq_matching": PaperPreset(
        key="p3_mcq_matching",
        part=3,
        label={
            "zh": "Part 3 · 单选 + 匹配（5+5）",
            "en": "Part 3 · Multiple choice + matching (5+5)",
        },
        groups=(GroupSpec("mcq_single", 5), GroupSpec("matching", 5)),
    ),
    "p3_sentence": PaperPreset(
        key="p3_sentence",
        part=3,
        label={
            "zh": "Part 3 · 句子填空（10 题）",
            "en": "Part 3 · Sentence completion (10)",
        },
        groups=(GroupSpec("sentence_completion", 10),),
    ),
    "p4_notes": PaperPreset(
        key="p4_notes",
        part=4,
        label={"zh": "Part 4 · 笔记填空（10 题）", "en": "Part 4 · Note completion (10)"},
        groups=(GroupSpec("note_completion", 10),),
    ),
    "p4_table": PaperPreset(
        key="p4_table",
        part=4,
        label={"zh": "Part 4 · 表格填空（10 题）", "en": "Part 4 · Table completion (10)"},
        groups=(GroupSpec("table_completion", 10),),
    ),
}

_DEFAULT_BY_PART = {1: "p1_form", 2: "p2_mcq_matching", 3: "p3_mcq_matching", 4: "p4_notes"}


def default_preset(part: int) -> str:
    return _DEFAULT_BY_PART.get(int(part), "p2_mcq_matching")


def get_preset(key: str) -> PaperPreset:
    try:
        return PRESETS[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown paper preset {key!r}; available: {', '.join(PRESETS)}"
        ) from exc


def presets_for_part(part: int) -> list[PaperPreset]:
    return [p for p in PRESETS.values() if p.part == int(part)]
