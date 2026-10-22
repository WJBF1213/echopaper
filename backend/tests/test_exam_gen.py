"""Tests for the experimental full exam-paper generator.

Task 9 narrowed this file to the subset that does not depend on the
deleted preset/part contract (see the T10 marker at the bottom).
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import exam_gen
from app.services.exam_gen import (
    content_ranges,
    generate_paper,
    is_rubric,
)
from app.services.exam_presets import QUESTION_TYPES


SENTENCES = [
    "You will hear a conversation between a student and a housing officer.",
    "Good morning I would like to ask about the deposit for the flat.",
    "The deposit is two hundred and fifty pounds in total.",
    "You will need to provide a passport and a bank statement.",
    "The flat is available from the first of September.",
    "There is a bus stop just outside the building.",
    "That is the end of part two. You now have ten minutes to check your answers.",
    "Thank you very much. Goodbye.",
]


def make_material(sentences: list[str]):
    words: list[dict] = []
    ranges: list[list[int]] = []
    idx = 0
    for text in sentences:
        start = idx
        for token in text.split():
            words.append({"w": token, "s": float(idx), "e": idx + 0.5, "p": 0.95})
            idx += 1
        ranges.append([start, idx - 1])
    return words, ranges


def sentence_text(words: list[dict], s: int, e: int) -> str:
    return " ".join(w["w"] for w in words[s : e + 1])


def run(coro):
    return asyncio.run(coro)


def test_rubrics_and_formulas_are_removed_from_content():
    words, ranges = make_material(SENTENCES)
    assert is_rubric(SENTENCES[0])
    assert is_rubric(SENTENCES[6])
    content = content_ranges(words, ranges)
    texts = [sentence_text(words, s, e) for s, e in content]
    assert all("You will hear" not in t for t in texts)
    assert all("That is the end" not in t for t in texts)
    assert all("Goodbye" not in t for t in texts)
    # Sentences 1-5 are content; the closing formula is dropped.
    assert len(content) == 5


def test_real_ielts_rubrics_are_recognised():
    """Regression: the span-only pipeline blanked these exact sentences."""
    cases = [
        "Test 3",
        "This is the IELTS listening test",
        "You will hear a number of different recordings and you will have to "
        "answer questions on what you hear",
        "There will be time for you to read the instructions and questions",
        "All the recordings will be played once only",
        "The test is in four parts",
        "At the end of the test you will be given 10 minutes to transfer your "
        "answers to the answer sheet",
        "Now turn to part 1",
        "Part 1",
        "First you have some time to look at questions 1 to 5",
        "Now listen carefully and answer questions 1 to 5",
        "You now have 30 seconds to check your answers to part two",
        "That is the end of part two",
    ]
    for text in cases:
        assert is_rubric(text), text


def test_real_test_intro_is_excluded_but_content_survives():
    intro = [
        "Test 3",
        "This is the IELTS listening test",
        "You will hear a number of different recordings and you will have to "
        "answer questions on what you hear",
        "At the end of the test you will be given 10 minutes to transfer your "
        "answers to the answer sheet",
        "We are looking for an administrative assistant",
    ]
    words, ranges = make_material(intro)
    content = content_ranges(words, ranges)
    texts = [sentence_text(words, s, e) for s, e in content]
    assert texts == ["We are looking for an administrative assistant"]
    assert all("10 minutes" not in t for t in texts)


def test_allocate_keeps_total_and_one_per_chunk():
    assert sum(exam_gen._allocate(10, [1, 2, 3])) == 10
    assert all(v >= 1 for v in exam_gen._allocate(10, [1, 2, 3]))
    assert sum(exam_gen._allocate(2, [5, 5, 5])) == 2


# ------------------------------------------- Task 7: registry rules + §8.1 order


def test_rules_render_from_registry_for_all_six_types(tmp_db):
    """Every registered type resolves its rules text from the registry
    (defaults, no variables) — the legacy preset-text fallback is gone."""
    for qtype in QUESTION_TYPES.values():
        for lang in ("zh", "en"):
            text = exam_gen._rules_text(tmp_db, qtype, lang)
            assert text  # non-empty
            assert "refused" in text  # refusal guidance rides in rules
            assert "{{" not in text


def test_rules_override_changes_task_frame(tmp_db):
    from app.services import prompts as prompts_svc

    words, ranges = make_material(SENTENCES)

    # completion: overridden rules replace the defaults in the task frame
    prompts_svc.set_override(tmp_db, "exam.rules.completion.zh", "覆盖后的填空规则")
    messages = exam_gen._build_messages(
        tmp_db, words, ranges,
        part=1, qtype=QUESTION_TYPES["completion"], ranges=[(0, 5)],
        allowed=[(0, 5)], count=3, lang="zh",
    )
    task = messages[2]["content"]
    assert "覆盖后的填空规则" in task
    assert "答案必须是给定转写中" not in task  # default rules replaced

    # non-completion type: same mechanism
    prompts_svc.set_override(tmp_db, "exam.rules.mcq_single.zh", "覆盖-MCQ规则")
    messages = exam_gen._build_messages(
        tmp_db, words, ranges,
        part=2, qtype=QUESTION_TYPES["mcq_single"], ranges=[(0, 5)],
        allowed=[(0, 5)], count=2, lang="zh",
    )
    assert "覆盖-MCQ规则" in messages[2]["content"]


def test_generate_paper_pending_blocks_api(tmp_db):
    """T9 transitional: the preset/part entry point refuses until Task 10
    rebuilds generation on the blocks API."""
    words, ranges = make_material(SENTENCES)
    with pytest.raises(exam_gen.ExamGenError):
        run(
            generate_paper(
                tmp_db, words, ranges, part=1,
                llm_cfg={"api_key": "test"},
            )
        )


# ----------------------------------------------- T10: restored on blocks API
# The preset/part-based generator tests were temporarily removed with the
# six-key registry swap (Task 9 deletes PRESETS / PaperPreset / GroupSpec /
# parts and stubs generate_paper). Task 10 rebuilds generation on the
# blocks API ({blocks: [{type, count}]}) and restores / rewrites:
#   - completion validation (edge/rubric/paraphrase/blank/leak guards)
#   - MCQ letter normalization + bad option counts
#   - matching option-pool uniqueness + evidence requirements
#   - visual block skip (map scene path per design §4.3)
#   - request validation (unknown type, count caps, word floors, refusal)
#   - three-part message shape through the generation entry point
