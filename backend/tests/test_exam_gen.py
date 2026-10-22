"""Tests for the experimental full exam-paper generator."""
from __future__ import annotations

import asyncio

import pytest

from app.services import exam_gen
from app.services.exam_gen import (
    content_ranges,
    generate_paper,
    is_rubric,
)
from app.services.exam_presets import GroupSpec, PaperPreset, QUESTION_TYPES
from app.services.exam_presets import PRESETS


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


def find_span(words: list[dict], text: str) -> tuple[int, int]:
    target = text.lower().split()
    tokens = [w["w"].lower().strip(".,!?;:") for w in words]
    for i in range(len(tokens) - len(target) + 1):
        if tokens[i : i + len(target)] == target:
            return i, i + len(target) - 1
    raise AssertionError(f"span not found: {text}")


def sentence_text(words: list[dict], s: int, e: int) -> str:
    return " ".join(w["w"] for w in words[s : e + 1])


def fake_chat(responses):
    """Return an async chat stub cycling through ``responses``."""

    async def _chat(cfg, system, user, schema):
        return responses.pop(0)

    return _chat


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


def test_completion_validation_blocks_edges_rubrics_and_paraphrases():
    words, ranges = make_material(SENTENCES)
    dep = find_span(words, "deposit")
    two = find_span(words, "two hundred")
    passport = find_span(words, "passport")
    september = find_span(words, "September")
    ten = find_span(words, "ten")

    def item(i0, i1, stem, answer):
        return {"stem": stem, "i0": i0, "i1": i1, "answer": answer}

    response = {
        "groups": [
            {
                "title": "Housing",
                "items": [
                    item(two[0], two[1], "The deposit is ______ in total.", "two hundred"),
                    # second word of the first content sentence: edge guard
                    item(dep[0], dep[1], "Good morning I would like to ask about the ______ for the flat.", "deposit"),
                    # rubric at the end
                    item(ten[0], ten[1], "You now have ______ minutes to check your answers.", "ten"),
                    item(passport[0], passport[1], "You will need to provide a ______ and a bank statement.", "passport"),
                    # paraphrased answer must be rejected
                    item(two[0], two[1], "The deposit is ______ in total.", "two hundred and fifty pounds"),
                    item(september[0], september[1], "The flat is available from the first of ______.", "September"),
                ],
            }
        ]
    }
    chat = fake_chat([response])

    PRESETS["test_completion"] = PaperPreset(
        key="test_completion",
        part=1,
        label={"zh": "test", "en": "test"},
        groups=(GroupSpec("form_completion", 3),),
    )
    try:
        paper = run(
            generate_paper(
                words,
                ranges,
                part=1,
                preset="test_completion",
                llm_cfg={"api_key": "test"},
                material_id="m1",
                chat_json_fn=chat,
            )
        )
    finally:
        PRESETS.pop("test_completion", None)
    answers = [i.answer for g in paper.groups for i in g.items]
    assert answers == ["two hundred", "passport", "September"]
    assert [i.number for g in paper.groups for i in g.items] == [1, 2, 3]
    assert all(i.evidence[0].t_end > i.evidence[0].t_start for g in paper.groups for i in g.items)
    assert any("保护" in w or "指令" in w or "句首" in w for w in paper.warnings)


def test_completion_rejects_missing_blank_and_leaked_answer():
    words, ranges = make_material(SENTENCES)
    two = find_span(words, "two hundred")
    response = {
        "groups": [
            {
                "items": [
                    {"stem": "The deposit is two hundred in total.", "i0": two[0], "i1": two[1], "answer": "two hundred"},
                    {"stem": "The deposit is ______ in total.", "i0": two[0], "i1": two[1], "answer": "two hundred"},
                ]
            }
        ]
    }
    PRESETS["test_one"] = PaperPreset(
        key="test_one",
        part=1,
        label={"zh": "test", "en": "test"},
        groups=(GroupSpec("form_completion", 1),),
    )
    try:
        paper = run(
            generate_paper(
                words, ranges, part=1, preset="test_one",
                llm_cfg={"api_key": "test"}, chat_json_fn=fake_chat([response]),
            )
        )
    finally:
        PRESETS.pop("test_one", None)
    items = [i for g in paper.groups for i in g.items]
    assert len(items) == 1
    assert items[0].stem.count("______") == 1
    assert items[0].answer == "two hundred"


def test_mcq_answer_is_normalized_to_letter_and_bad_options_rejected():
    words, ranges = make_material(SENTENCES)
    two = find_span(words, "two hundred")
    s2 = ranges[2]
    good = {
        "stem": "How much is the deposit?",
        "options": ["One hundred pounds", "Two hundred pounds", "Three hundred pounds"],
        "answer": "Two hundred pounds",
        "evidence": [{"i0": s2[0], "i1": s2[1], "quote": " ".join(w["w"] for w in words[s2[0] : s2[1] + 1])}],
    }
    bad = {
        "stem": "What is needed?",
        "options": ["Passport", "Bank statement"],
        "answer": "A",
        "evidence": [{"i0": s2[0], "i1": s2[1]}],
    }
    PRESETS["test_mcq"] = PaperPreset(
        key="test_mcq",
        part=2,
        label={"zh": "test", "en": "test"},
        groups=(GroupSpec("mcq_single", 2),),
    )
    try:
        paper = run(
            generate_paper(
                words, ranges, part=2, preset="test_mcq",
                llm_cfg={"api_key": "test"},
                chat_json_fn=fake_chat([{"groups": [{"items": [good, bad]}]}]),
            )
        )
    finally:
        PRESETS.pop("test_mcq", None)
    items = [i for g in paper.groups for i in g.items]
    assert len(items) == 1
    assert items[0].answer == "B"
    assert items[0].options[1] == "Two hundred pounds"


def test_matching_requires_unique_options_and_evidence():
    words, ranges = make_material(SENTENCES)
    s2 = ranges[2]
    quote = " ".join(w["w"] for w in words[s2[0] : s2[1] + 1])
    response = {
        "groups": [
            {
                "title": "Facilities",
                "options": ["Deposit", "Passport", "September", "Bus stop"],
                "items": [
                    {"stem": "What is refundable?", "answer": "A", "evidence": [{"i0": s2[0], "i1": s2[1], "quote": quote}]},
                    {"stem": "When is it available?", "answer": "Deposit", "evidence": [{"i0": s2[0], "i1": s2[1]}]},
                    {"stem": "What is outside?", "answer": "D", "evidence": [{"i0": s2[0], "i1": s2[1]}]},
                ],
            }
        ]
    }
    PRESETS["test_matching"] = PaperPreset(
        key="test_matching",
        part=2,
        label={"zh": "test", "en": "test"},
        groups=(GroupSpec("matching", 3),),
    )
    try:
        paper = run(
            generate_paper(
                words, ranges, part=2, preset="test_matching",
                llm_cfg={"api_key": "test"}, chat_json_fn=fake_chat([response]),
            )
        )
    finally:
        PRESETS.pop("test_matching", None)
    items = [i for g in paper.groups for i in g.items]
    assert [i.answer for i in items] == ["A", "D"]
    assert paper.groups[0].options == [
        "A. Deposit",
        "B. Passport",
        "C. September",
        "D. Bus stop",
    ]


def test_visual_preset_is_skipped_with_a_warning():
    words, ranges = make_material(SENTENCES)
    s2 = ranges[2]
    mcq = {
        "stem": "How much is the deposit?",
        "options": ["One hundred pounds", "Two hundred pounds", "Three hundred pounds"],
        "answer": "B",
        "evidence": [{"i0": s2[0], "i1": s2[1]}],
    }
    paper = run(
        generate_paper(
            words, ranges, part=2, preset="p2_map_mcq",
            llm_cfg={"api_key": "test"},
            chat_json_fn=fake_chat([{"groups": [{"items": [mcq]}]}]),
        )
    )
    assert any("底图" in w for w in paper.warnings)
    assert paper.total_items == 1
    assert paper.groups[0].type_key == "mcq_single"


def test_preset_part_mismatch_is_rejected():
    words, ranges = make_material(SENTENCES)
    with pytest.raises(exam_gen.ExamGenError):
        run(
            generate_paper(
                words, ranges, part=4, preset="p1_form",
                llm_cfg={"api_key": "test"},
            )
        )


def test_allocate_keeps_total_and_one_per_chunk():
    assert sum(exam_gen._allocate(10, [1, 2, 3])) == 10
    assert all(v >= 1 for v in exam_gen._allocate(10, [1, 2, 3]))
    assert sum(exam_gen._allocate(2, [5, 5, 5])) == 2
