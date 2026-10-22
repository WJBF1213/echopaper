"""Single source of truth for every LLM prompt (Task 5).

All prompt texts for the exam pipeline live in ``ALL_PROMPTS``. The legacy
copies in ``exam_gen._SYSTEM_ZH/_SYSTEM_EN/_USER_ZH/_USER_EN`` and in
``exam_presets.rules_zh/rules_en`` are migrated here VERBATIM; the only
edit is that ``str.format`` interpolation points (``{var}``) became literal
``{{var}}`` placeholders. ``exam_gen`` keeps its own constants until it
switches to this registry (Task 7); this module is the new source of truth.

Migration and split notes
-------------------------
* ``exam.system.<locale>``  <- ``exam_gen._SYSTEM_ZH`` / ``_SYSTEM_EN``.
  No placeholders.

* ``exam.stable_frame.<locale>`` + ``exam.task_frame.<locale>`` split the
  legacy user message ``exam_gen._USER_ZH`` / ``_USER_EN`` at the candidate
  block:
  - ``stable_frame`` = the transcript block + the candidate block. It
    depends only on the material, so it is identical for every generation
    request over that material and can serve as a stable prompt prefix.
  - ``task_frame`` = the request header (part / type label / item count /
    paper instruction) + the type requirements + the audio-order note +
    the JSON schema line. Everything that varies per request.
  Hence ``{{transcript}}`` and ``{{candidates}}`` live in stable_frame,
  while ``{{part}}``, ``{{label}}``, ``{{count}}``, ``{{instruction}}``,
  ``{{rules}}``, ``{{gap}}`` and ``{{schema}}`` live in task_frame. The
  legacy ``{schema_hint}`` name was shortened to ``{{schema}}``. How the
  two frames are assembled into one user message is decided by the
  generator (Task 7), not here.

* ``exam.rules.<type>.<locale>`` <- ``exam_presets.rules_zh`` / ``rules_en``
  of every question type registered today (13 types). Completion rules
  keep their ``{{max_words}}`` placeholder; ``word_limit`` never occurred
  in the legacy texts, so it is not declared as a variable.

Rendering performs LITERAL ``str.replace`` per variable — never
``str.format`` or f-strings — because templates and variable values are
full of JSON braces that would crash format-based interpolation.

Overrides persist through the existing settings table (``app.db``) under
the key ``prompt_overrides`` as a JSON dict ``{prompt_key: text}``.

Self-contained: stdlib + ``app.db`` helpers only.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app import db

PROMPTS_VERSION: int = 1

#: settings-table key holding the ``{prompt_key: override_text}`` JSON dict.
OVERRIDE_SETTING_KEY = "prompt_overrides"


class PromptError(Exception):
    """Unknown prompt key, bad render variables, or a broken template."""


@dataclass(frozen=True)
class PromptSpec:
    """One registry entry: a localized prompt template plus its metadata."""

    key: str
    title_zh: str
    title_en: str
    category: str
    variables: tuple[str, ...]
    default: str


# --------------------------------------------------------------- migrated
# texts (verbatim from exam_gen.py / exam_presets.py; only ``{var}`` became
# ``{{var}}`` — keep Chinese Chinese and English English when editing)

_SYSTEM_ZH = """你是剑桥雅思听力命题人，负责按官方题型生成可直接用于练习的整套题目。
硬性规则：
1. 只能使用转写中明确出现的事实，不得编造人名、数字、地点、观点或因果关系。
2. 所有 evidence 必须是转写中逐字连续的词跨度；i0/i1 必须在给定范围内，
   quote 必须与这些词逐字一致（只允许大小写和标点差异）。
3. 禁止使用考试指令、转场语、问候和告别句。输入已经剔除这些句子；
   如果仍引用到，该题作废。
4. 题目顺序必须与音频顺序一致，题与题之间至少间隔 5 个词。
5. 不要集中挖开头或结尾：开头的寒暄/介绍和结尾的总结/道别都不是考点。
6. 题干用英文，答案必须符合该题型的字数限制。
7. 只返回 JSON 对象，不要解释性文字。"""

_SYSTEM_EN = """You are a Cambridge IELTS Listening item writer. Generate a
complete, practice-ready set of items for the requested question type.
Hard rules:
1. Use only facts explicitly present in the transcript; never invent names,
   numbers, places, opinions or causal links.
2. Every evidence entry must be a verbatim word span. i0/i1 must be inside
   the supplied ranges, and quote must match those words exactly (case and
   punctuation differences are tolerated).
3. Never use exam rubrics, part transitions, greetings or sign-offs. They
   have been removed from the input; any item citing one is invalid.
4. Items must follow audio order, with at least 5 words between two answers.
5. Do not cluster items at the very start or the very end. Opening small
   talk and closing summaries are not test points.
6. Write stems in English and respect the word limit of the type.
7. Return a JSON object only; no prose."""

_STABLE_FRAME_ZH = """可用于命题的转写内容（每行一句，词前的数字是全局词索引）：
{{transcript}}

候选答案（词性/置信度预筛，仅供参考，也可选候选之外的跨度）：
{{candidates}}"""

_STABLE_FRAME_EN = """Transcript usable for items (one sentence per line; numbers are global word indices):
{{transcript}}

Pre-filtered candidate answers (optional hints; other spans are allowed):
{{candidates}}"""

_TASK_FRAME_ZH = """Part {{part}} · {{label}}
题型：{{label}}
组内题量：{{count}}
试卷指令（英文）：{{instruction}}

题型要求：
{{rules}}

请按音频顺序出题，至少间隔 {{gap}} 个词；不要把题目集中在开头或结尾。
返回 JSON：{{schema}}"""

_TASK_FRAME_EN = """Part {{part}} · {{label}}
Question type: {{label}}
Items requested: {{count}}
Paper instruction: {{instruction}}

Type requirements:
{{rules}}

Follow audio order with at least {{gap}} words between answers; do not cluster
items at the very start or end.
Return JSON: {{schema}}"""

_COMPLETION_RULES_ZH = (
    "答案必须是给定转写中逐字连续的一段，且不超过 {{max_words}} 个词"
    "（数字整体算一个词：250、two hundred and fifty 均算一个）。"
    "不得改写、翻译或补全。"
    "stem 用英文原句，把答案位置替换为 ______；form/note 可另给 label。"
    "不要考句首两词、考试指令、问候与告别语。"
)
_COMPLETION_RULES_EN = (
    "The answer must be a verbatim, contiguous span from the transcript of "
    "at most {{max_words}} word(s), where a whole number counts as one word "
    "(250 and 'two hundred and fifty' both count as one). Never paraphrase, "
    "translate or complete it. Write the stem as the original English "
    "sentence with the answer replaced by ______; form/note items may add a "
    "label. Never test the first two words of a sentence, exam rubrics, "
    "greetings or sign-offs."
)

#: (type key, label zh, label en, rules zh, rules en) — verbatim from
#: ``exam_presets.QUESTION_TYPES`` in registration order.
_RULES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "form_completion",
        "表单填空",
        "Form completion",
        _COMPLETION_RULES_ZH + "表单题要给出字段标签 label（如 Name、Deposit）。",
        _COMPLETION_RULES_EN
        + " Form items must include a short field label (Name, Deposit, ...).",
    ),
    (
        "note_completion",
        "笔记填空",
        "Note completion",
        _COMPLETION_RULES_ZH + "按主题分组（每组 2-4 题），组标题用英文。",
        _COMPLETION_RULES_EN
        + " Group items by topic (2-4 per group) with an English group title.",
    ),
    (
        "table_completion",
        "表格填空",
        "Table completion",
        _COMPLETION_RULES_ZH + "每题的 label 写所在行/列的提示词。",
        _COMPLETION_RULES_EN
        + " Each item's label should name its row or column cue.",
    ),
    (
        "sentence_completion",
        "句子填空",
        "Sentence completion",
        _COMPLETION_RULES_ZH + "题干必须是原文中的完整句子。",
        _COMPLETION_RULES_EN
        + " The stem must be a complete sentence taken from the transcript.",
    ),
    (
        "summary_completion",
        "摘要填空",
        "Summary completion",
        _COMPLETION_RULES_ZH
        + "摘要可用同义改写，但每个答案仍须是原文逐字跨度；不要连续挖相邻词。",
        _COMPLETION_RULES_EN
        + " The summary may paraphrase, but each answer stays verbatim and "
        "two blanks must never be adjacent.",
    ),
    (
        "flowchart_completion",
        "流程图填空",
        "Flow-chart completion",
        _COMPLETION_RULES_ZH + "按流程顺序出题，每题 label 写流程步骤名。",
        _COMPLETION_RULES_EN + " Follow the process order; each label names its step.",
    ),
    (
        "short_answer",
        "简答题",
        "Short answer",
        _COMPLETION_RULES_ZH
        + "题干写成英文疑问句，答案必须是原文中能直接回答该问题的词跨度。",
        _COMPLETION_RULES_EN
        + " Write an English question; the answer span must directly answer it.",
    ),
    (
        "mcq_single",
        "单选题",
        "Multiple choice (single answer)",
        "每题 3 个选项、恰好 1 个正确。正确项必须由原文明确支持；"
        "干扰项必须与原文矛盾或原文未提及，不能同样成立。"
        "evidence 引用支持正确答案的原文词跨度；题干用英文。",
        "Exactly 3 options and 1 correct answer. The correct option must "
        "be explicitly supported by the transcript; distractors must be "
        "contradicted or unsupported, never also true. Cite the supporting "
        "span as evidence. Write the stem in English.",
    ),
    (
        "mcq_multi",
        "多选题（选两项）",
        "Multiple choice (two answers)",
        "每题 5 个选项、恰好 2 个正确。两个正确项都必须由原文支持；"
        "干扰项不得成立。answer 写成 \"A,C\"；evidence 引用支持两个正确项的词跨度。",
        "Exactly 5 options and 2 correct answers. Both must be supported "
        "by the transcript; distractors must not be true. Return answer "
        'as "A,C" and cite spans supporting both.',
    ),
    (
        "matching",
        "匹配题",
        "Matching",
        "先给出 4-6 个选项组成的选项池 options，再出 3-6 道匹配题。"
        "每个选项最多使用一次，答案必须由原文明确支持；"
        "evidence 引用支持该匹配的词跨度。",
        "Provide a shared option list of 4-6 options, then 3-6 matching "
        "items. Each option is used at most once; every match must be "
        "explicitly supported by the transcript.",
    ),
    (
        "map_labelling",
        "地图标注",
        "Map labelling",
        "地图题需要一张地图图像；纯音频无法生成，必须由用户提供底图。",
        "Map labelling needs a map image; audio alone cannot generate it. "
        "The user must supply the base map.",
    ),
    (
        "plan_labelling",
        "平面图标注",
        "Plan labelling",
        "平面图题需要一张平面图；纯音频无法生成，必须由用户提供底图。",
        "Plan labelling needs a plan image; audio alone cannot generate "
        "it. The user must supply the base plan.",
    ),
    (
        "diagram_labelling",
        "示意图标注",
        "Diagram labelling",
        "示意图题需要一张示意图；纯音频无法生成，必须由用户提供底图。",
        "Diagram labelling needs a diagram image; audio alone cannot "
        "generate it. The user must supply the base diagram.",
    ),
)


def _rule_specs() -> tuple[PromptSpec, ...]:
    specs: list[PromptSpec] = []
    for type_key, label_zh, label_en, rules_zh, rules_en in _RULES:
        specs.append(
            PromptSpec(
                key=f"exam.rules.{type_key}.zh",
                title_zh=f"题型要求 · {label_zh}",
                title_en=f"Rules · {label_en}",
                category="rules",
                variables=("max_words",) if "{{max_words}}" in rules_zh else (),
                default=rules_zh,
            )
        )
        specs.append(
            PromptSpec(
                key=f"exam.rules.{type_key}.en",
                title_zh=f"题型要求 · {label_zh}",
                title_en=f"Rules · {label_en}",
                category="rules",
                variables=("max_words",) if "{{max_words}}" in rules_en else (),
                default=rules_en,
            )
        )
    return tuple(specs)


ALL_PROMPTS: tuple[PromptSpec, ...] = (
    PromptSpec(
        key="exam.system.zh",
        title_zh="系统提示 · 中文",
        title_en="System prompt · Chinese",
        category="system",
        variables=(),
        default=_SYSTEM_ZH,
    ),
    PromptSpec(
        key="exam.system.en",
        title_zh="系统提示 · 英文",
        title_en="System prompt · English",
        category="system",
        variables=(),
        default=_SYSTEM_EN,
    ),
    PromptSpec(
        key="exam.stable_frame.zh",
        title_zh="稳定框架（转写+候选）· 中文",
        title_en="Stable frame (transcript + candidates) · Chinese",
        category="frame",
        variables=("transcript", "candidates"),
        default=_STABLE_FRAME_ZH,
    ),
    PromptSpec(
        key="exam.stable_frame.en",
        title_zh="稳定框架（转写+候选）· 英文",
        title_en="Stable frame (transcript + candidates) · English",
        category="frame",
        variables=("transcript", "candidates"),
        default=_STABLE_FRAME_EN,
    ),
    PromptSpec(
        key="exam.task_frame.zh",
        title_zh="任务框架（题型+输出）· 中文",
        title_en="Task frame (type + output) · Chinese",
        category="frame",
        variables=("part", "label", "count", "instruction", "rules", "gap",
                   "schema"),
        default=_TASK_FRAME_ZH,
    ),
    PromptSpec(
        key="exam.task_frame.en",
        title_zh="任务框架（题型+输出）· 英文",
        title_en="Task frame (type + output) · English",
        category="frame",
        variables=("part", "label", "count", "instruction", "rules", "gap",
                   "schema"),
        default=_TASK_FRAME_EN,
    ),
) + _rule_specs()

_BY_KEY: dict[str, PromptSpec] = {spec.key: spec for spec in ALL_PROMPTS}


# --------------------------------------------------------------- overrides


def _overrides(conn: sqlite3.Connection) -> dict:
    value = db.get_setting(conn, OVERRIDE_SETTING_KEY)
    return value if isinstance(value, dict) else {}


def _lookup(key: str) -> PromptSpec:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise PromptError(f"Unknown prompt key: {key!r}")
    return spec


def get_prompt(conn: sqlite3.Connection, key: str) -> str:
    """Return the override text for ``key`` when set, else the default."""
    spec = _lookup(key)
    override = _overrides(conn).get(key)
    if isinstance(override, str) and override:
        return override
    return spec.default


def set_override(
    conn: sqlite3.Connection, key: str, text: str | None
) -> None:
    """Persist (``text``) or clear (``None`` / empty string) an override."""
    _lookup(key)
    overrides = _overrides(conn)
    if text is None or text == "":
        overrides.pop(key, None)
    else:
        overrides[key] = text
    db.set_setting(conn, OVERRIDE_SETTING_KEY, overrides)


def render_prompt(
    conn: sqlite3.Connection, base_key: str, locale: str, **variables: object
) -> str:
    """Render ``f"{base_key}.{locale}"`` with literal ``{{var}}`` replacement.

    Never uses ``str.format``: templates and values are full of JSON braces.
    Raises :class:`PromptError` when the key is unknown, when the caller
    passes variables the spec does not declare (or omits declared ones), or
    when the effective template (override if set, else default) lacks a
    declared ``{{variable}}`` placeholder.
    """
    key = f"{base_key}.{locale}"
    spec = _lookup(key)
    extra = sorted(set(variables) - set(spec.variables))
    if extra:
        raise PromptError(
            f"Undeclared variable(s) {extra} for {key}; "
            f"declared: {list(spec.variables)}"
        )
    missing = [name for name in spec.variables if name not in variables]
    if missing:
        raise PromptError(f"Missing variable(s) {missing} for {key}")
    template = get_prompt(conn, key)
    for name in spec.variables:
        token = "{{" + name + "}}"
        if token not in template:
            raise PromptError(
                f"Template for {key} is missing the {token} placeholder"
            )
        template = template.replace(token, str(variables[name]))
    return template


def list_prompts(conn: sqlite3.Connection) -> list[dict]:
    """Catalogue every prompt: metadata plus default/current/customized."""
    overrides = _overrides(conn)
    entries: list[dict] = []
    for spec in ALL_PROMPTS:
        override = overrides.get(spec.key)
        customized = isinstance(override, str) and bool(override)
        entries.append(
            {
                "key": spec.key,
                "title": spec.title_zh if spec.key.endswith(".zh")
                else spec.title_en,
                "category": spec.category,
                "variables": list(spec.variables),
                "default": spec.default,
                "current": override if customized else spec.default,
                "customized": customized,
            }
        )
    return entries
