"""Single source of truth for every LLM prompt (Task 5).

All prompt texts for the exam pipeline live in ``ALL_PROMPTS``. The
frames were migrated verbatim from the legacy ``exam_gen`` constants; the
per-type rules texts were rewritten by the Task 9 six-key swap (see the
notes below). ``exam_gen`` consumes only this registry.

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

* ``exam.rules.<type>.<locale>`` <- the per-type requirements texts. The
  Task 9 six-key swap replaced the 13 legacy entries with one pair per
  registered type (mcq_single / mcq_multi / matching / completion /
  short_answer / map_labelling). The new texts adapt the legacy rules,
  add per-item ``word_limit`` and layout-suggestion guidance for
  ``completion``, and every one ends with the refusal-guidance paragraph
  of design §4.5 (return ``refused`` with a one-line reason instead of
  forcing items the transcript cannot support). The texts declare no
  ``{{variables}}`` — completion's word limit is per-item guidance now,
  not a template slot. ``PROMPTS_VERSION`` moved 1 -> 2, which changes
  every LLM cache key (intended).

Rendering performs LITERAL ``str.replace`` per variable — never
``str.format`` or f-strings — because templates and variable values are
full of JSON braces that would crash format-based interpolation.

Overrides persist through the existing settings table (``app.db``) under
the key ``prompt_overrides`` as a JSON dict ``{prompt_key: text}``.

Self-contained: stdlib + ``app.db`` helpers + the type registry's names.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app import db
from app.services.exam_presets import QUESTION_TYPES

PROMPTS_VERSION: int = 2

#: settings-table key holding the ``{prompt_key: override_text}`` JSON dict.
OVERRIDE_SETTING_KEY = "prompt_overrides"

# ------------------------------------------------- §4.5 precheck texts
# User-facing skip reasons for the generator's deterministic prechecks
# (design §4.5: code-level refusals that save an LLM call). They are NOT
# LLM prompts -- never rendered into a message and not registry entries --
# but they live here so every generation-facing text sits in one module.
# The map *scene* texts are deliberately absent: they arrive with the
# scene task (design §4.3).

#: Prefix marking a reason as a code-level precheck (zero LLM calls).
PRECHECK_TAG = "[precheck]"

PRECHECK_REASON_TOO_SHORT = {
    "zh": "转写仅 {words} 词，{label}至少需要 {min_words} 词的转写",
    "en": "transcript has only {words} words; {label} needs at least "
          "{min_words}",
}

PRECHECK_REASON_NO_SPATIAL = {
    "zh": "转写中没有空间方位描述，不适合{label}",
    "en": "no spatial description in the transcript; unsuitable for {label}",
}


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

#: type key -> (rules zh, rules en). Every text ends with its refusal
#: paragraph (design §4.5); the parenthetical examples are adapted per
#: type, the core sentence stays recognizable so overrides stay comparable.
_RULES_TEXTS: dict[str, tuple[str, str]] = {
    "mcq_single": (
        "每题 3 个选项、恰好 1 个正确。正确项必须由原文明确支持；"
        "干扰项必须与原文矛盾或原文未提及，不能同样成立。"
        "evidence 引用支持正确答案的原文词跨度；题干用英文。\n"
        "若转写内容不适合本题型（如缺少可构造独立干扰项的明确事实、"
        "信息密度不足以出足量题目），不要硬凑——返回 refused 并给一句话原因。",
        "Exactly 3 options and 1 correct answer per item. The correct "
        "option must be explicitly supported by the transcript; "
        "distractors must be contradicted or unsupported, never also "
        "true. Cite the supporting span as evidence. Write the stem in "
        "English.\n"
        "If the transcript does not suit this type (no distinct facts to "
        "build independent distractors, or too little material for the "
        "requested item count), do not force it — return refused with a "
        "one-line reason.",
    ),
    "mcq_multi": (
        "每题 5 个选项、恰好 2 个正确。两个正确项都必须由原文支持；"
        "干扰项不得成立。answer 写成 \"A,C\"；"
        "evidence 引用支持两个正确项的词跨度。\n"
        "若转写内容不适合本题型（如缺少可并列支撑两个正确项的要点、"
        "信息密度不足以出足量题目），不要硬凑——返回 refused 并给一句话原因。",
        "Exactly 5 options and 2 correct answers per item. Both correct "
        "options must be supported by the transcript; distractors must "
        "not be true. Return the answer as \"A,C\" and cite spans "
        "supporting both.\n"
        "If the transcript does not suit this type (not enough parallel "
        "points to support two correct answers, or too little material "
        "for the requested item count), do not force it — return refused "
        "with a one-line reason.",
    ),
    "matching": (
        "先给出 4-6 个选项组成的选项池 options，再出 3-6 道匹配题。"
        "每个选项最多使用一次，答案必须由原文明确支持；"
        "evidence 引用支持该匹配的词跨度。\n"
        "若转写内容不适合本题型（如缺少可匹配的选项特征、"
        "选项之间区分度不足、信息密度不足以出足量题目），"
        "不要硬凑——返回 refused 并给一句话原因。",
        "Provide a shared option list of 4-6 options, then 3-6 matching "
        "items. Each option is used at most once; every match must be "
        "explicitly supported by the transcript, with the supporting span "
        "cited as evidence.\n"
        "If the transcript does not suit this type (no matchable option "
        "features, options without enough contrast, or too little "
        "material for the requested item count), do not force it — "
        "return refused with a one-line reason.",
    ),
    "completion": (
        "答案必须是给定转写中逐字连续的一段"
        "（数字整体算一个词：250、two hundred and fifty 均算一个）。"
        "不得改写、翻译或补全。stem 用英文原句，把答案位置替换为 ______。"
        "按考点自行决定每题答案长度（1-3 词），并在 word_limit 写明"
        "（如 ONE WORD ONLY / NO MORE THAN TWO WORDS AND/OR A NUMBER）。"
        "根据内容为每组建议版式 layout：对话问答用 form；列举对比用 table；"
        "讲座要点用 notes；单独完整句用 sentence；摘要改写用 summary；"
        "流程顺序用 flowchart。不要考句首两词、考试指令、问候与告别语。\n"
        "若转写内容不适合本题型（如缺少值得挖空的实词、"
        "信息密度不足以出足量题目），不要硬凑——返回 refused 并给一句话原因。",
        "The answer must be a verbatim, contiguous span from the "
        "transcript (a whole number counts as one word: 250 and 'two "
        "hundred and fifty' both count as one). Never paraphrase, "
        "translate or complete it. Write the stem as the original "
        "English sentence with the answer replaced by ______. Choose "
        "each answer's length to fit its test point (1-3 words) and "
        "state it in word_limit (e.g. ONE WORD ONLY / NO MORE THAN TWO "
        "WORDS AND/OR A NUMBER). Suggest the layout that fits each "
        "group's content: form for dialogue Q&A, table for lists and "
        "contrasts, notes for lecture points, sentence for standalone "
        "sentences, summary for paraphrased digests, flowchart for "
        "processes. Never test the first two words of a sentence, exam "
        "rubrics, greetings or sign-offs.\n"
        "If the transcript does not suit this type (not enough content "
        "words worth blanking, or too little material for the requested "
        "item count), do not force it — return refused with a one-line "
        "reason.",
    ),
    "short_answer": (
        "题干写成英文疑问句，答案必须是原文中能直接回答该问题的逐字词跨度"
        "（不超过 3 个词，数字整体算一个词），不得改写或翻译。\n"
        "若转写内容不适合本题型（如缺少能以疑问句直接指向的事实点、"
        "信息密度不足以出足量题目），不要硬凑——返回 refused 并给一句话原因。",
        "Write each stem as an English question; the answer must be a "
        "verbatim span from the transcript (at most 3 words, a whole "
        "number counts as one) that directly answers it. Never paraphrase "
        "or translate.\n"
        "If the transcript does not suit this type (no facts a question "
        "can point at directly, or too little material for the requested "
        "item count), do not force it — return refused with a one-line "
        "reason.",
    ),
    "map_labelling": (
        "地图题按说话人的空间描述出题：场景由节点和路径构成，"
        "每个空位对应图上一个待标注的位置，answer 是选项字母；"
        "evidence 引用支撑该位置的原文词跨度"
        "（in/on the left、next to、opposite、at the bottom、between "
        "等空间描述优先作为考点）。\n"
        "若转写内容不适合本题型（如转写中没有空间语言、"
        "说话人没有描述位置关系），不要硬凑——返回 refused 并给一句话原因。",
        "Build map items from the speaker's spatial description: the "
        "scene is nodes and paths, each blank is a point on the map to "
        "be labelled, the answer is an option letter, and evidence "
        "cites the span supporting that location (spatial phrases such "
        "as in/on the left, next to, opposite, at the bottom, between "
        "make the best test points).\n"
        "If the transcript does not suit this type (no spatial "
        "language, or the speaker never describes position relations), "
        "do not force it — return refused with a one-line reason.",
    ),
}

_missing_rules = set(QUESTION_TYPES) - set(_RULES_TEXTS)
if _missing_rules:
    raise RuntimeError(
        f"prompt rules text missing for question types: {sorted(_missing_rules)}"
    )


def _rule_specs() -> tuple[PromptSpec, ...]:
    specs: list[PromptSpec] = []
    for type_key, qtype in QUESTION_TYPES.items():
        rules_zh, rules_en = _RULES_TEXTS[type_key]
        for loc, rules in (("zh", rules_zh), ("en", rules_en)):
            specs.append(
                PromptSpec(
                    key=f"exam.rules.{type_key}.{loc}",
                    title_zh=f"题型要求 · {qtype.name_zh}",
                    title_en=f"Rules · {qtype.name_en}",
                    category="rules",
                    variables=("max_words",) if "{{max_words}}" in rules else (),
                    default=rules,
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
    """Catalogue every prompt: metadata plus default/current/customized.

    ``title`` picks by the key's own locale suffix; ``title_zh`` /
    ``title_en`` carry both localized titles so the API layer can select
    one via the request's Accept-Language (Task 6).
    """
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
                "title_zh": spec.title_zh,
                "title_en": spec.title_en,
                "category": spec.category,
                "variables": list(spec.variables),
                "default": spec.default,
                "current": override if customized else spec.default,
                "customized": customized,
            }
        )
    return entries
