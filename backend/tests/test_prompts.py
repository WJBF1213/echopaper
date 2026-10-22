"""Task 5 tests: prompt registry, literal ``{{var}}`` rendering, overrides.

The brief announced 15 registry entries, but the arithmetic (3 frames x 2
locales + N types x 2 locales = 6 + 2N) is always even, so 15 was never
reachable. ``exam_presets`` registers 13 question types today, so the
registry holds 6 + 26 = 32 entries; this test pins the real key set.
"""
import pytest

from app.services import prompts
from app.services.prompts import PromptError


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

    rules_zh = prompts.render_prompt(
        tmp_db, "exam.rules.form_completion", "zh", max_words=2
    )
    assert "{{max_words}}" not in rules_zh
    assert "不超过 2 个词" in rules_zh


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
    for base in ("exam.system", "exam.stable_frame", "exam.task_frame"):
        for loc in ("zh", "en"):
            expected.add(f"{base}.{loc}")
    for type_key in (
        "form_completion",
        "note_completion",
        "table_completion",
        "sentence_completion",
        "summary_completion",
        "flowchart_completion",
        "short_answer",
        "mcq_single",
        "mcq_multi",
        "matching",
        "map_labelling",
        "plan_labelling",
        "diagram_labelling",
    ):
        for loc in ("zh", "en"):
            expected.add(f"exam.rules.{type_key}.{loc}")

    assert keys == expected
    assert prompts.PROMPTS_VERSION == 1
    # Every default template actually carries its declared placeholders.
    for spec in prompts.ALL_PROMPTS:
        for var in spec.variables:
            assert "{{" + var + "}}" in spec.default, spec.key
        assert spec.key.endswith((".zh", ".en"))
