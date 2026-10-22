"""Tests for the blocks-based paper generator (design §4, Task 10).

``generate_paper`` takes ``blocks=[{type, count}]`` in user order: the
order is the zone order, matching keeps one shared option pool, and the
whole paper is renumbered by earliest evidence. completion carries a
per-item ``word_limit`` (validated against the actual answer's word
count) and a per-item ``layout``; the printed group instruction is
synthesized from the loosest limit in the group (design §4.1).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.services import exam_gen
from app.services.exam_gen import (
    GenerateResult,
    content_ranges,
    generate_paper,
    is_rubric,
)
from app.services.exam_presets import QUESTION_TYPES
from app.services.llm import ChatUsage


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
# 170 words: clears every type's min_words floor (matching 150, mcq 120).
LONG = SENTENCES * 2


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


def as_material(words: list[dict], ranges: list[list[int]], mid: str = "m1") -> dict:
    return {
        "id": mid,
        "words_json": json.dumps(words),
        "sentences_json": json.dumps(ranges),
    }


# Spatial-language talk (map precheck, design §4.5): every sentence
# carries one of the positional cue phrases the map rules text names
# (in/on the left, next to, opposite, at the bottom, between, ...).
MAP_TALK = [
    "Now we are standing at the entrance at the bottom of the plan.",
    "The gift shop is on the left opposite the ticket desk.",
    "The cafe is next to the main hall between the two galleries.",
    "The sculpture garden lies behind the north wing.",
    "The lecture theatre is at the end of the corridor on the right.",
]


def find_span(words: list[dict], text: str, occurrence: int = 1) -> tuple[int, int]:
    target = text.lower().split()
    tokens = [w["w"].lower().strip(".,!?;:") for w in words]
    seen = 0
    for i in range(len(tokens) - len(target) + 1):
        if tokens[i : i + len(target)] == target:
            seen += 1
            if seen == occurrence:
                return i, i + len(target) - 1
    raise AssertionError(f"span not found (occurrence {occurrence}): {text}")


def sentence_text(words: list[dict], s: int, e: int) -> str:
    return " ".join(w["w"] for w in words[s : e + 1])


def fake_cached_chat(responses, capture=None):
    """Async stub shaped like ``llm.cached_chat_json`` (3-tuple return).

    Each ``responses`` entry is a response dict (default usage, cache
    miss) or an explicit ``(obj, ChatUsage, from_cache)`` tuple. Calls
    past the end of the list get an empty groups object so the retry
    round terminates.
    """
    async def _chat(conn, cfg, messages, *, task, **kwargs):
        if capture is not None:
            capture.append({"task": task, "messages": [dict(m) for m in messages]})
        item = responses.pop(0) if responses else {"groups": []}
        if isinstance(item, tuple):
            return item
        return item, ChatUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=0), False

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


# ------------------------------------------------- blocks API (design §4.4)


def test_blocks_two_types_generate_ordered_zones(tmp_db):
    """Two blocks in user order: block 1 reads the first audio zone, block 2
    the second; groups keep block order, the paper is numbered 1..N, and
    matching prints one letter-prefixed option pool."""
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    passport = find_span(words, "passport")
    two_hundred_2 = find_span(words, "two hundred", 2)
    passport_2 = find_span(words, "passport", 2)
    september_2 = find_span(words, "September", 2)

    mcq = {"groups": [{"title": "Housing", "items": [
        {
            "stem": "How much is the deposit?",
            "options": ["One hundred pounds", "Two hundred pounds",
                        "Three hundred pounds"],
            "answer": "Two hundred pounds",
            "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}],
        },
        {
            "stem": "What must you provide?",
            "options": ["A passport", "A visa", "A driving licence"],
            "answer": "A",
            "evidence": [{"i0": passport[0], "i1": passport[1]}],
        },
    ]}]}
    matching = {"groups": [{"title": "Facilities", "options": [
        "Deposit", "Passport", "September", "Bus stop",
    ], "items": [
        {"stem": "Which amount is due?", "answer": "A",
         "evidence": [{"i0": two_hundred_2[0], "i1": two_hundred_2[1]}]},
        {"stem": "Which document?", "answer": "B",
         "evidence": [{"i0": passport_2[0], "i1": passport_2[1]}]},
        {"stem": "Which month?", "answer": "C",
         "evidence": [{"i0": september_2[0], "i1": september_2[1]}]},
    ]}]}

    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "mcq_single", "count": 2}, {"type": "matching", "count": 3}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([mcq, matching]),
    ))
    assert isinstance(result, GenerateResult)
    assert result.skipped == []

    groups = result.paper["groups"]
    assert [g["type"] for g in groups] == ["mcq_single", "matching"]
    assert groups[0]["title"] == "Housing"
    assert groups[0]["instruction"] == "Choose the correct letter, A, B or C."
    assert groups[1]["instruction"] == "Match each item with the correct option, A-F."
    assert groups[1]["options"] == [
        "A. Deposit", "B. Passport", "C. September", "D. Bus stop",
    ]
    mcq_items = groups[0]["items"]
    assert [i["answer"] for i in mcq_items] == ["B", "A"]
    # Block 1 items are all heard before block 2 items (zones).
    first_block_end = mcq_items[-1]["evidence"][0]["i1"]
    assert all(
        it["evidence"][0]["i0"] > first_block_end for it in groups[1]["items"]
    )
    numbers = [it["number"] for g in groups for it in g["items"]]
    assert numbers == [1, 2, 3, 4, 5]
    assert result.paper["total_items"] == 5

    # Part/preset are gone from the paper shape (design §4.2).
    assert "part" not in result.paper
    assert "preset" not in result.paper

    # Every block-level LLM call is task-labelled and cached (Task 7 seam).
    assert [u["task"] for u in result.usage] == [
        "exam:mcq_single", "exam:matching",
    ]


def test_completion_word_limit_checked_against_answer(tmp_db):
    """The declared word_limit is validated against the answer's actual word
    count; a number phrase counts as one word (design §4.1)."""
    words, ranges = make_material(LONG)
    bank = find_span(words, "bank statement")
    two_hundred = find_span(words, "two hundred")
    september = find_span(words, "September")

    response = {"groups": [{"title": "Housing", "layout": "notes", "items": [
        # Declared ONE WORD ONLY but the answer is two words -> rejected.
        {"stem": "You will need to provide a passport and a ______.",
         "i0": bank[0], "i1": bank[1], "answer": "bank statement",
         "word_limit": "ONE WORD ONLY"},
        # Same answer under a two-word limit -> accepted (normalized).
        {"stem": "You will need to provide a passport and a ______.",
         "i0": bank[0], "i1": bank[1], "answer": "bank statement",
         "word_limit": "no more than two words"},
        # A spelled number counts as one word even under ONE WORD ONLY.
        {"stem": "The deposit is ______ in total.",
         "i0": two_hundred[0], "i1": two_hundred[1], "answer": "two hundred",
         "word_limit": "ONE WORD ONLY"},
        {"stem": "The flat is available from the first of ______.",
         "i0": september[0], "i1": september[1], "answer": "September",
         "word_limit": "NO MORE THAN THREE WORDS"},
    ]}]}
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 3}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response]),
    ))
    items = result.paper["groups"][0]["items"]
    assert [i["answer"] for i in items] == [
        "two hundred", "bank statement", "September",
    ]
    assert [i["word_limit"] for i in items] == [
        "ONE WORD ONLY", "NO MORE THAN TWO WORDS", "NO MORE THAN THREE WORDS",
    ]
    # The over-limit item was refused, not silently kept.
    assert any("word_limit" in w for w in result.paper["warnings"])


def test_completion_word_limit_required_and_parsable(tmp_db):
    words, ranges = make_material(LONG)
    september = find_span(words, "September")
    response = {"groups": [{"items": [
        {"stem": "The flat is available from the first of ______.",
         "i0": september[0], "i1": september[1], "answer": "September"},

    ]}]}
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([
            response,
            {"groups": [{"items": [
                {"stem": "The flat is available from the first of ______.",
                 "i0": september[0], "i1": september[1], "answer": "September",
                 "word_limit": "ABOUT TEN WORDS", "layout": "notes"},
            ]}]},
        ]),
    ))
    # Both the missing and the unrecognized limit are refused; the
    # deterministic top-up fills the quota instead.
    assert any("word_limit" in w for w in result.paper["warnings"])


def test_completion_layout_passthrough_and_hint_override(tmp_db):
    """Item-level layout wins over the group's; layout_hint forces every
    completion item; unknown layouts fall back to notes."""
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    september = find_span(words, "September")

    def item(span, answer, stem, layout=None):
        it = {"stem": stem, "i0": span[0], "i1": span[1], "answer": answer,
              "word_limit": "NO MORE THAN TWO WORDS"}
        if layout:
            it["layout"] = layout
        return it

    response = {"groups": [{"title": "Housing", "layout": "form", "items": [
        item(two_hundred, "two hundred", "The deposit is ______ in total.",
             layout="table"),
        item(september, "September",
             "The flat is available from the first of ______."),
    ]}]}
    material = as_material(words, ranges)

    result = run(generate_paper(
        tmp_db, material, [{"type": "completion", "count": 2}],
        {"api_key": "test"}, lang="zh", chat_fn=fake_cached_chat([response]),
    ))
    items = result.paper["groups"][0]["items"]
    assert [i["layout"] for i in items] == ["table", "form"]
    # Instruction noun follows the first item's layout.
    assert result.paper["groups"][0]["instruction"].startswith(
        "Complete the table below."
    )

    # layout_hint overrides every completion item (design §4.1).
    result = run(generate_paper(
        tmp_db, material, [{"type": "completion", "count": 2}],
        {"api_key": "test"}, lang="zh", layout_hint="notes",
        chat_fn=fake_cached_chat([response]),
    ))
    items = result.paper["groups"][0]["items"]
    assert [i["layout"] for i in items] == ["notes", "notes"]
    assert result.paper["groups"][0]["instruction"].startswith(
        "Complete the notes below."
    )

    # An unrecognized layout suggestion falls back to the generic notes.
    bogus = {"groups": [{"items": [
        item(september, "September",
             "The flat is available from the first of ______.", layout="mind-map"),
    ]}]}
    result = run(generate_paper(
        tmp_db, material, [{"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([bogus, {"groups": []}]),
    ))
    layouts = [i["layout"] for g in result.paper["groups"] for i in g["items"]]
    assert all(l == "notes" for l in layouts)


def test_completion_instruction_synthesized_from_loosest_limit(tmp_db):
    """The group instruction uses the loosest word_limit in the group and
    the layout's official noun (design §4.1)."""
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    september = find_span(words, "September")
    bank = find_span(words, "bank statement")

    def response(limits, layout):
        spans = [two_hundred, september, bank][: len(limits)]
        stems = [
            "The deposit is ______ in total.",
            "The flat is available from the first of ______.",
            "You will need to provide a passport and a ______.",
        ]
        return {"groups": [{"layout": layout, "items": [
            {"stem": stems[i], "i0": s[0], "i1": s[1],
             "answer": " ".join(w["w"] for w in words[s[0]: s[1] + 1]),
             "word_limit": lim, "layout": layout}
            for i, (s, lim) in enumerate(zip(spans, limits))
        ]}]}

    material = as_material(words, ranges)

    result = run(generate_paper(
        tmp_db, material, [{"type": "completion", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response(
            ["ONE WORD ONLY", "NO MORE THAN THREE WORDS"], "notes")]),
    ))
    assert result.paper["groups"][0]["instruction"] == (
        "Complete the notes below. Write NO MORE THAN THREE WORDS "
        "for each answer."
    )

    result = run(generate_paper(
        tmp_db, material, [{"type": "completion", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response(
            ["ONE WORD ONLY", "NO MORE THAN TWO WORDS"], "sentence")]),
    ))
    assert result.paper["groups"][0]["instruction"] == (
        "Complete the sentences below. Write NO MORE THAN TWO WORDS "
        "for each answer."
    )

    result = run(generate_paper(
        tmp_db, material, [{"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response(["ONE WORD ONLY"], "flowchart")]),
    ))
    assert result.paper["groups"][0]["instruction"] == (
        "Complete the flow-chart below. Write ONE WORD ONLY for each answer."
    )


def test_short_answer_keeps_fixed_three_word_limit(tmp_db):
    """short_answer stays a separate span type with the fixed 3-word limit
    and its official instruction (design §4.2)."""
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    bank = find_span(words, "bank statement")
    response = {"groups": [{"items": [
        {"stem": "The deposit is ______ in total.",
         "i0": two_hundred[0], "i1": two_hundred[1], "answer": "two hundred"},
        {"stem": "You will need to provide a passport and a ______.",
         "i0": bank[0], "i1": bank[1], "answer": "bank statement"},
    ]}]}
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "short_answer", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response]),
    ))
    group = result.paper["groups"][0]
    assert group["type"] == "short_answer"
    assert group["instruction"] == (
        "Answer the questions below. Write NO MORE THAN THREE WORDS "
        "for each answer."
    )
    assert all(i["word_limit"] == "NO MORE THAN THREE WORDS"
               for i in group["items"])
    assert all(i["layout"] is None for i in group["items"])


def test_regenerate_variation_marker_lands_in_task_frame(tmp_db):
    """regenerate=True appends ``variation: <papers+1>`` to the task frame
    (the last message), busting the local llm_cache key; the stable prefix
    stays untouched. The paper itself may succeed or fail (the deterministic
    top-up can fill an empty LLM response) -- only the marker matters."""
    words, ranges = make_material(LONG)
    material = as_material(words, ranges)

    captured = []
    try:
        run(generate_paper(
            tmp_db, material, [{"type": "completion", "count": 1}],
            {"api_key": "test"}, lang="zh", regenerate=True,
            chat_fn=fake_cached_chat([], capture=captured),
        ))
    except exam_gen.ExamGenError:
        pass
    assert captured
    first = captured[0]["messages"]
    assert [m["role"] for m in first] == ["system", "user", "user"]
    assert "variation: 1" in first[-1]["content"]
    # The marker rides only the task frame, never the cached prefix.
    assert "variation:" not in first[0]["content"]
    assert "variation:" not in first[1]["content"]

    captured.clear()
    try:
        run(generate_paper(
            tmp_db, material, [{"type": "completion", "count": 1}],
            {"api_key": "test"}, lang="zh", regenerate=False,
            chat_fn=fake_cached_chat([], capture=captured),
        ))
    except exam_gen.ExamGenError:
        pass
    assert captured
    assert all("variation:" not in m["content"]
               for c in captured for m in c["messages"])


def test_generate_result_usage_populated_from_calls(tmp_db):
    """GenerateResult.usage records every block-level cached_chat_json
    return, with the task label and the cache-hit flag."""
    words, ranges = make_material(LONG)
    september = find_span(words, "September")
    response = {"groups": [{"items": [
        {"stem": "The flat is available from the first of ______.",
         "i0": september[0], "i1": september[1], "answer": "September",
         "word_limit": "ONE WORD ONLY", "layout": "notes"},
    ]}]}
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([(
            response,
            ChatUsage(prompt_tokens=100, completion_tokens=20, cached_tokens=50),
            True,
        )]),
    ))
    assert result.usage == [{
        "task": "exam:completion",
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "cached_tokens": 50,
        "cached_hit": True,
    }]


# ------------------------------------- suitability refusal (design §4.5)


def test_refused_response_skips_block_with_one_llm_call(tmp_db):
    """A refused block-level response skips the block: no chunk retries,
    no repair round, no deterministic top-up -- exactly one LLM call is
    spent on the block (design §4.5)."""
    words, ranges = make_material(LONG)
    captured = []
    with pytest.raises(exam_gen.ExamAllRefusedError) as excinfo:
        run(generate_paper(
            tmp_db, as_material(words, ranges),
            [{"type": "mcq_single", "count": 2}],
            {"api_key": "test"}, lang="zh",
            chat_fn=fake_cached_chat(
                [{"refused": True, "reason": "转写缺少可构造干扰项的事实"}],
                capture=captured,
            ),
        ))
    assert excinfo.value.skipped == [
        {"type": "mcq_single", "reason": "转写缺少可构造干扰项的事实"}
    ]
    # The only block refused -> all-refused signal (the API layer turns
    # this into 400 with the skipped body). One call, no retry path.
    assert [c["task"] for c in captured] == ["exam:mcq_single"]


def test_refused_flag_alongside_items_is_not_a_refusal(tmp_db):
    """An items-bearing response never counts as refused, whatever the
    refused flag says -- refusal is detected structurally, not by the
    produced count."""
    words, ranges = make_material(LONG)
    september = find_span(words, "September")
    response = {
        "refused": True,  # ignored: a groups array is an items payload
        "groups": [{"items": [
            {"stem": "The flat is available from the first of ______.",
             "i0": september[0], "i1": september[1], "answer": "September",
             "word_limit": "ONE WORD ONLY", "layout": "notes"},
        ]}],
    }
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response]),
    ))
    assert result.skipped == []
    assert result.paper["total_items"] == 1


def test_mixed_refusal_and_success_keeps_partial_paper(tmp_db):
    """One block refused + one block succeeding: the successful group
    stands, and the refused type is listed in skipped with its reason."""
    words, ranges = make_material(LONG)
    september_2 = find_span(words, "September", 2)
    completion = {"groups": [{"items": [
        {"stem": "The flat is available from the first of ______.",
         "i0": september_2[0], "i1": september_2[1], "answer": "September",
         "word_limit": "NO MORE THAN THREE WORDS"},
    ]}]}
    captured = []
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "mcq_single", "count": 2}, {"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat(
            [{"refused": True, "reason": "不适合单选"}, completion],
            capture=captured,
        ),
    ))
    assert result.skipped == [{"type": "mcq_single", "reason": "不适合单选"}]
    assert [g["type"] for g in result.paper["groups"]] == ["completion"]
    assert result.paper["total_items"] == 1
    assert [c["task"] for c in captured] == [
        "exam:mcq_single", "exam:completion",
    ]


def test_precheck_short_transcript_skips_without_llm_call(tmp_db):
    """The min_words precheck refuses the block before any LLM call and
    lands in skipped with the [precheck] prefix -- no longer a warning."""
    # 85 words: completion (80) fits, mcq_single (120) does not.
    words, ranges = make_material(SENTENCES)
    september = find_span(words, "September")
    completion = {"groups": [{"items": [
        {"stem": "The flat is available from the first of ______.",
         "i0": september[0], "i1": september[1], "answer": "September",
         "word_limit": "ONE WORD ONLY", "layout": "notes"},
    ]}]}
    captured = []
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 1}, {"type": "mcq_single", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([completion], capture=captured),
    ))
    assert [g["type"] for g in result.paper["groups"]] == ["completion"]
    assert len(result.skipped) == 1
    skip = result.skipped[0]
    assert skip["type"] == "mcq_single"
    assert skip["reason"].startswith("[precheck]")
    assert "120" in skip["reason"] and "词" in skip["reason"]
    # The old warning-based rejection is gone from the paper.
    assert all("单选题" not in w for w in result.paper["warnings"])
    # Zero LLM calls were spent on the floored block.
    assert [c["task"] for c in captured] == ["exam:completion"]

    # Every block floored -> all-refused signal (the API layer turns this
    # into 400 with the skipped body), still with zero LLM calls.
    tiny_words, tiny_ranges = make_material(["Hello there my friend."])
    tiny_captured = []
    with pytest.raises(exam_gen.ExamAllRefusedError) as excinfo:
        run(generate_paper(
            tmp_db, as_material(tiny_words, tiny_ranges),
            [{"type": "completion", "count": 3}],
            {"api_key": "test"}, lang="zh",
            chat_fn=fake_cached_chat([], capture=tiny_captured),
        ))
    assert excinfo.value.skipped[0]["reason"].startswith("[precheck]")
    assert tiny_captured == []


def test_precheck_map_without_spatial_language_skips(tmp_db):
    """map_labelling over a transcript with no spatial sentences is
    precheck-refused with zero LLM calls spent on the block."""
    # 255 words (over map's 200 floor) but no spatial cue phrases.
    words, ranges = make_material(SENTENCES * 3)
    september = find_span(words, "September")
    completion = {"groups": [{"items": [
        {"stem": "The flat is available from the first of ______.",
         "i0": september[0], "i1": september[1], "answer": "September",
         "word_limit": "ONE WORD ONLY", "layout": "notes"},
    ]}]}
    captured = []
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 1}, {"type": "map_labelling", "count": 5}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([completion], capture=captured),
    ))
    assert len(result.skipped) == 1
    skip = result.skipped[0]
    assert skip["type"] == "map_labelling"
    assert skip["reason"].startswith("[precheck]")
    assert "空间" in skip["reason"]
    assert [c["task"] for c in captured] == ["exam:completion"]


def test_map_with_spatial_language_waits_for_scene_path(tmp_db):
    """Spatial language present: the map block still cannot run until the
    scene path lands (§4.3, later task) -- skipped by precheck, zero
    LLM calls (the message changes when the two-step generation arrives)."""
    words, ranges = make_material(MAP_TALK * 4)  # 228 words, spatial-rich
    captured = []
    with pytest.raises(exam_gen.ExamAllRefusedError) as excinfo:
        run(generate_paper(
            tmp_db, as_material(words, ranges),
            [{"type": "map_labelling", "count": 5}],
            {"api_key": "test"}, lang="zh",
            chat_fn=fake_cached_chat([], capture=captured),
        ))
    skip = excinfo.value.skipped[0]
    assert skip["type"] == "map_labelling"
    assert skip["reason"].startswith("[precheck]")
    assert "场景" in skip["reason"]
    assert captured == []


def test_shortfall_marks_group_partial_not_skipped(tmp_db):
    """Insufficiency is not refusal (design §4.5): a block that ends under
    quota after the retry path marks its group partial, never skipped."""
    # 170 words: clears matching's 150-word floor.
    words, ranges = make_material(LONG)
    two_hundred_2 = find_span(words, "two hundred", 2)
    passport_2 = find_span(words, "passport", 2)
    response = {"groups": [{"title": "Facilities", "options": [
        "Deposit", "Passport", "September", "Bus stop",
    ], "items": [
        {"stem": "Which amount is due?", "answer": "A",
         "evidence": [{"i0": two_hundred_2[0], "i1": two_hundred_2[1]}]},
        {"stem": "Which document?", "answer": "B",
         "evidence": [{"i0": passport_2[0], "i1": passport_2[1]}]},
    ]}]}

    # 2 of 3 requested survive; the repair round returns the same two and
    # the letter-dedup merge keeps the total at 2 -> partial, not skipped.
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "matching", "count": 3}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response, response]),
    ))
    group = result.paper["groups"][0]
    assert len(group["items"]) == 2
    assert group["partial"] is True
    assert result.skipped == []

    # A block that meets its quota carries partial: false.
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "matching", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response]),
    ))
    group = result.paper["groups"][0]
    assert len(group["items"]) == 2
    assert group["partial"] is False
    assert result.skipped == []


# ------------------------------------- restored validator defenses (pre-T9)


def test_completion_validation_blocks_edges_rubrics_and_paraphrases(tmp_db):
    words, ranges = make_material(LONG)
    dep = find_span(words, "deposit")
    two = find_span(words, "two hundred")
    passport = find_span(words, "passport")
    september = find_span(words, "September")
    ten = find_span(words, "ten")

    def item(i0, i1, stem, answer, limit="NO MORE THAN TWO WORDS"):
        return {"stem": stem, "i0": i0, "i1": i1, "answer": answer,
                "word_limit": limit}

    response = {
        "groups": [
            {
                "title": "Housing",
                "items": [
                    item(two[0], two[1], "The deposit is ______ in total.",
                         "two hundred"),
                    # second word of the first content sentence: edge guard
                    item(dep[0], dep[1],
                         "Good morning I would like to ask about the ______ "
                         "for the flat.", "deposit"),
                    # answer inside a spoken rubric
                    item(ten[0], ten[1],
                         "You now have ______ minutes to check your answers.",
                         "ten", limit="ONE WORD ONLY"),
                    item(passport[0], passport[1],
                         "You will need to provide a ______ and a bank "
                         "statement.", "passport"),
                    # a longer verbatim span snapped from the same quote
                    # exceeds its declared limit
                    item(two[0], two[1], "The deposit is ______ in total.",
                         "two hundred and fifty pounds"),
                    item(september[0], september[1],
                         "The flat is available from the first of ______.",
                         "September", limit="NO MORE THAN THREE WORDS"),
                ],
            }
        ]
    }
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 3}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response]),
    ))
    answers = [i["answer"] for g in result.paper["groups"] for i in g["items"]]
    assert answers == ["two hundred", "passport", "September"]
    assert [i["number"] for g in result.paper["groups"] for i in g["items"]] == [1, 2, 3]
    assert all(
        i["evidence"][0]["t_end"] > i["evidence"][0]["t_start"]
        for g in result.paper["groups"] for i in g["items"]
    )
    assert any(
        "保护" in w or "指令" in w or "句首" in w
        for w in result.paper["warnings"]
    )


def test_completion_enforces_min_gap_between_answers(tmp_db):
    """No-adjacent-blanks (legacy micro-guardrail re-encoded on the blocks
    API): two completion answers closer than MIN_GAP_WORDS words cannot
    both stand -- the later one is dropped with a warning."""
    words, ranges = make_material(LONG)
    passport = find_span(words, "passport")
    bank = find_span(words, "bank statement")
    september = find_span(words, "September")

    response = {"groups": [{"items": [
        # "passport" and "bank statement" sit 2 words apart in one sentence.
        {"stem": "You will need to provide a passport and a ______.",
         "i0": bank[0], "i1": bank[1], "answer": "bank statement",
         "word_limit": "NO MORE THAN TWO WORDS"},
        {"stem": "You will need to provide a ______ and a bank statement.",
         "i0": passport[0], "i1": passport[1], "answer": "passport",
         "word_limit": "ONE WORD ONLY"},
        {"stem": "The flat is available from the first of ______.",
         "i0": september[0], "i1": september[1], "answer": "September",
         "word_limit": "NO MORE THAN THREE WORDS"},
    ]}]}
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response, {"groups": []}]),
    ))
    answers = [i["answer"] for g in result.paper["groups"] for i in g["items"]]
    # The earlier "passport" stands, the adjacent "bank statement" is
    # dropped, and the distant "September" survives.
    assert answers == ["passport", "September"]
    assert any("过近" in w for w in result.paper["warnings"])


def test_completion_rejects_missing_blank_and_leaked_answer(tmp_db):
    words, ranges = make_material(LONG)
    two = find_span(words, "two hundred")
    response = {
        "groups": [
            {
                "items": [
                    {"stem": "The deposit is two hundred in total.",
                     "i0": two[0], "i1": two[1], "answer": "two hundred",
                     "word_limit": "NO MORE THAN TWO WORDS"},
                    {"stem": "The deposit is ______ in total.",
                     "i0": two[0], "i1": two[1], "answer": "two hundred",
                     "word_limit": "NO MORE THAN TWO WORDS"},
                ]
            }
        ]
    }
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "completion", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response]),
    ))
    items = [i for g in result.paper["groups"] for i in g["items"]]
    assert len(items) == 1
    assert items[0]["stem"].count("______") == 1
    assert items[0]["answer"] == "two hundred"


def test_mcq_answer_is_normalized_to_letter_and_bad_options_rejected(tmp_db):
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    good = {
        "stem": "How much is the deposit?",
        "options": ["One hundred pounds", "Two hundred pounds",
                    "Three hundred pounds"],
        "answer": "Two hundred pounds",
        "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}],
    }
    bad = {
        "stem": "What is needed?",
        "options": ["Passport", "Bank statement"],
        "answer": "A",
        "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}],
    }
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "mcq_single", "count": 2}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([{"groups": [{"items": [good, bad]}]},
                                  {"groups": []}]),
    ))
    items = [i for g in result.paper["groups"] for i in g["items"]]
    assert len(items) == 1
    assert items[0]["answer"] == "B"
    assert items[0]["options"][1] == "Two hundred pounds"


def test_matching_requires_unique_options_and_evidence(tmp_db):
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    quote = " ".join(w["w"] for w in words[two_hundred[0]: two_hundred[1] + 1])
    response = {
        "groups": [
            {
                "title": "Facilities",
                "options": ["Deposit", "Passport", "September", "Bus stop"],
                "items": [
                    {"stem": "Which amount is refundable?", "answer": "A",
                     "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1],
                                   "quote": quote}]},
                    {"stem": "When is it available?", "answer": "Deposit",
                     "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}]},
                    {"stem": "What is outside?", "answer": "D",
                     "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}]},
                ],
            }
        ]
    }
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "matching", "count": 3}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([response, {"groups": []}]),
    ))
    items = [i for g in result.paper["groups"] for i in g["items"]]
    assert [i["answer"] for i in items] == ["A", "D"]
    assert result.paper["groups"][0]["options"] == [
        "A. Deposit", "B. Passport", "C. September", "D. Bus stop",
    ]


def test_matching_two_blocks_share_one_pool(tmp_db):
    """matching never splits its option pool: a second matching block
    reuses the first block's pool (letters keep one meaning)."""
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    september_2 = find_span(words, "September", 2)
    pool = ["Deposit", "Passport", "September", "Bus stop"]
    first = {"groups": [{"title": "One", "options": pool, "items": [
        {"stem": "Which amount is due?", "answer": "A",
         "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}]},
    ]}]}
    # Second block invents its own pool; the shared pool must win.
    second = {"groups": [{"title": "Two",
                          "options": ["Alpha", "Beta", "Gamma", "Delta"],
                          "items": [
        {"stem": "Which month?", "answer": "C",
         "evidence": [{"i0": september_2[0], "i1": september_2[1]}]},
    ]}]}
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "matching", "count": 1}, {"type": "matching", "count": 1}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([first, second]),
    ))
    groups = result.paper["groups"]
    assert len(groups) == 2
    for group in groups:
        assert group["options"] == [
            "A. Deposit", "B. Passport", "C. September", "D. Bus stop",
        ]
    assert groups[1]["items"][0]["answer"] == "C"
    assert groups[1]["items"][0]["answer_text"] == "September"


def test_map_block_precheck_skips_into_skipped_list(tmp_db):
    """A map block never spends an LLM call while the scene path is a
    later task (design §4.3): the skip lands in skipped with the
    [precheck] prefix (migrated out of paper.warnings, T10 review)."""
    # 170 words: under map_labelling's 200-word floor.
    words, ranges = make_material(LONG)
    two_hundred = find_span(words, "two hundred")
    mcq = {
        "stem": "How much is the deposit?",
        "options": ["One hundred pounds", "Two hundred pounds",
                    "Three hundred pounds"],
        "answer": "B",
        "evidence": [{"i0": two_hundred[0], "i1": two_hundred[1]}],
    }
    captured = []
    result = run(generate_paper(
        tmp_db, as_material(words, ranges),
        [{"type": "mcq_single", "count": 1}, {"type": "map_labelling", "count": 5}],
        {"api_key": "test"}, lang="zh",
        chat_fn=fake_cached_chat([{"groups": [{"items": [mcq]}]}],
                                 capture=captured),
    ))
    assert result.paper["total_items"] == 1
    assert result.paper["groups"][0]["type"] == "mcq_single"
    assert len(result.skipped) == 1
    assert result.skipped[0]["type"] == "map_labelling"
    assert result.skipped[0]["reason"].startswith("[precheck]")
    assert "200" in result.skipped[0]["reason"]
    # No LLM call was spent on the map block.
    assert [c["task"] for c in captured] == ["exam:mcq_single"]


def test_generate_paper_rejects_bad_blocks(tmp_db):
    words, ranges = make_material(SENTENCES)
    material = as_material(words, ranges)
    with pytest.raises(exam_gen.ExamGenError):
        run(generate_paper(tmp_db, material, [], {"api_key": "test"}))
    with pytest.raises(exam_gen.ExamGenError):
        run(generate_paper(
            tmp_db, material, [{"type": "no_such_type", "count": 2}],
            {"api_key": "test"},
        ))
    with pytest.raises(exam_gen.ExamGenError):
        run(generate_paper(
            tmp_db, material, [{"type": "completion", "count": 0}],
            {"api_key": "test"},
        ))
    with pytest.raises(exam_gen.ExamGenError):
        run(generate_paper(
            tmp_db, material, [{"type": "completion", "count": 11}],
            {"api_key": "test"},
        ))
    with pytest.raises(exam_gen.ExamGenError):
        run(generate_paper(
            tmp_db, material, [{"type": "completion", "count": 1}],
            {"api_key": "test"}, layout_hint="mind-map",
        ))


def test_generate_paper_sends_three_part_messages(tmp_db):
    """§8.1 pinned at the generator: every call is exactly
    [system, stable frame (transcript + candidates), task frame]."""
    words, ranges = make_material(LONG)
    captured = []
    try:
        run(generate_paper(
            tmp_db, as_material(words, ranges),
            [{"type": "completion", "count": 1}],
            {"api_key": "test"}, lang="zh",
            chat_fn=fake_cached_chat([], capture=captured),
        ))
    except exam_gen.ExamGenError:
        pass  # empty LLM responses may leave the paper empty

    assert captured
    for call in captured:
        messages = call["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "user"]
        assert messages[0]["content"].startswith("你是剑桥雅思听力命题人")
        # stable frame: transcript + candidates; task frame: rules + JSON
        assert "可用于命题的转写内容" in messages[1]["content"]
        assert "候选答案" in messages[1]["content"]
        assert "题型要求" in messages[2]["content"]
        assert "返回 JSON：" in messages[2]["content"]
        assert "填空题" in messages[2]["content"]


def test_completion_word_limit_rides_schema_hint():
    """The completion schema hint tells the LLM about word_limit/layout."""
    hint = exam_gen._schema_hint(QUESTION_TYPES["completion"])
    assert "word_limit" in hint
    assert "layout" in hint
    short = exam_gen._schema_hint(QUESTION_TYPES["short_answer"])
    assert "word_limit" not in short
