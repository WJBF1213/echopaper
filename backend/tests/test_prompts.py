"""Task 5 tests: prompt registry, literal ``{{var}}`` rendering, overrides.

Task 9 swapped the 13 legacy type-rule entries for the six-key registry
(mcq_single / mcq_multi / matching / completion / short_answer /
map_labelling), each carrying a refusal-guidance paragraph (design §4.5).
Task 12 added the map scene prompt (``scene.user``, design §4.3). The
registry therefore holds 3 frames x 2 locales + 6 rules x 2 locales +
1 scene x 2 locales = 20 entries; ``PROMPTS_VERSION`` moved to 3 so LLM
cache keys change.
"""
import pytest

from app.services import prompts
from app.services.prompts import PromptError

NEW_TYPE_KEYS = (
    "mcq_single",
    "mcq_multi",
    "matching",
    "completion",
    "short_answer",
    "map_labelling",
)

OLD_TYPE_KEYS = (
    "form_completion",
    "note_completion",
    "table_completion",
    "sentence_completion",
    "summary_completion",
    "flowchart_completion",
    "plan_labelling",
    "diagram_labelling",
)


def test_render_replaces_variables(tmp_db):
    schema = '{"groups":[{"title":"...","items":[{"stem":"... ______ ..."}]}]}'
    text = prompts.render_prompt(
        tmp_db,
        "exam.task_frame",
        "zh",
        part=1,
        label="表单填空",
        count=10,
        instruction="Complete the form below.",
        rules="规则文本",
        gap=5,
        schema=schema,
    )
    assert "{{" not in text
    assert "Part 1 · 表单填空" in text
    assert "组内题量：10" in text
    assert "规则文本" in text
    # JSON braces in variable values must pass through untouched.
    assert schema in text

    # English frame + a placeholder-bearing rules entry.
    en = prompts.render_prompt(
        tmp_db,
        "exam.task_frame",
        "en",
        part=2,
        label="Matching",
        count=5,
        instruction="Match each item.",
        rules="rules text",
        gap=5,
        schema=schema,
    )
    assert "Items requested: 5" in en
    assert schema in en

    # New six-key rules render without variables; refusal guidance rides
    # at the end of every rules text.
    rules_zh = prompts.render_prompt(tmp_db, "exam.rules.completion", "zh")
    assert "refused" in rules_zh
    assert "不要硬凑" in rules_zh


def test_render_missing_placeholder_raises(tmp_db):
    # Caller omits a declared variable -> a placeholder would survive.
    with pytest.raises(PromptError):
        prompts.render_prompt(tmp_db, "exam.stable_frame", "zh", transcript="t")
    # Caller passes a variable the spec does not declare.
    with pytest.raises(PromptError):
        prompts.render_prompt(tmp_db, "exam.system", "zh", bogus="x")
    # Unknown key (and unknown locale collapses to an unknown key).
    with pytest.raises(PromptError):
        prompts.render_prompt(tmp_db, "exam.nope", "zh")
    with pytest.raises(PromptError):
        prompts.get_prompt(tmp_db, "exam.system.fr")
    # An override template that dropped a declared placeholder must not
    # silently render with the raw ``{{var}}`` left inside.
    prompts.set_override(tmp_db, "exam.stable_frame.zh", "no placeholders")
    with pytest.raises(PromptError):
        prompts.render_prompt(
            tmp_db, "exam.stable_frame", "zh", transcript="t", candidates="c"
        )


def test_override_roundtrip(tmp_db):
    default = prompts.get_prompt(tmp_db, "exam.system.zh")
    assert default.startswith("你是剑桥雅思听力命题人")

    prompts.set_override(tmp_db, "exam.system.zh", "你是测试命题人。")
    assert prompts.get_prompt(tmp_db, "exam.system.zh") == "你是测试命题人。"
    assert "测试命题人" in prompts.render_prompt(tmp_db, "exam.system", "zh")

    prompts.set_override(tmp_db, "exam.system.zh", None)
    assert prompts.get_prompt(tmp_db, "exam.system.zh") == default

    # Empty string also restores the default.
    prompts.set_override(tmp_db, "exam.system.zh", "x")
    prompts.set_override(tmp_db, "exam.system.zh", "")
    assert prompts.get_prompt(tmp_db, "exam.system.zh") == default

    with pytest.raises(PromptError):
        prompts.set_override(tmp_db, "exam.nope.zh", "x")


def test_list_prompts_customized_flag(tmp_db):
    entries = prompts.list_prompts(tmp_db)
    assert entries, "registry must not be empty"
    fields = {"key", "title", "category", "variables", "default", "current",
              "customized"}
    assert all(fields <= set(e) for e in entries)

    by_key = {e["key"]: e for e in entries}
    entry = by_key["exam.system.en"]
    assert entry["customized"] is False
    assert entry["current"] == entry["default"]

    prompts.set_override(tmp_db, "exam.system.en", "Override text.")
    by_key = {e["key"]: e for e in prompts.list_prompts(tmp_db)}
    entry = by_key["exam.system.en"]
    assert entry["customized"] is True
    assert entry["current"] == "Override text."


def test_registry_contains_all_keys():
    keys = {s.key for s in prompts.ALL_PROMPTS}
    assert len(keys) == len(prompts.ALL_PROMPTS), "duplicate registry keys"

    expected = set()
    for base in ("exam.system", "exam.stable_frame", "exam.task_frame",
                 "scene.user"):
        for loc in ("zh", "en"):
            expected.add(f"{base}.{loc}")
    for type_key in NEW_TYPE_KEYS:
        for loc in ("zh", "en"):
            expected.add(f"exam.rules.{type_key}.{loc}")

    # 3 frames x 2 locales + 6 rules x 2 locales + scene.user x 2 = 20.
    assert keys == expected
    assert len(keys) == 20
    # The 13-key legacy type registry is fully gone.
    for old in OLD_TYPE_KEYS:
        assert f"exam.rules.{old}.zh" not in keys
        assert f"exam.rules.{old}.en" not in keys

    assert prompts.PROMPTS_VERSION == 3
    # Every rules default ends with its refusal guidance paragraph
    # (design §4.5): "refused" plus the locale's do-not-force wording.
    for spec in prompts.ALL_PROMPTS:
        if spec.category == "rules":
            assert "refused" in spec.default, spec.key
            if spec.key.endswith(".zh"):
                assert "不要硬凑" in spec.default, spec.key
            else:
                assert "do not force it" in spec.default, spec.key
    # The scene prompt (§4.3 step 1) also knows how to refuse.
    scene = next(s for s in prompts.ALL_PROMPTS if s.key == "scene.user.zh")
    assert scene.category == "scene"
    assert "refused" in scene.default
    assert "不要硬凑" in scene.default
    # Every default template actually carries its declared placeholders.
    for spec in prompts.ALL_PROMPTS:
        for var in spec.variables:
            assert "{{" + var + "}}" in spec.default, spec.key
        assert spec.key.endswith((".zh", ".en"))
