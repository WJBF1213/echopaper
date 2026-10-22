"""Task B6 tests: hybrid question generation pipeline.

Addendum coverage: context budget chunking by sentence boundaries with
per-chunk stateless calls, global gap/order constraints at merge time.
"""
import pytest

from app.services import question_gen as qg
from app.services.question_gen import (
    QuestionGenError,
    derive_word_limit,
    generate_set,
    validate_items,
)

WORDS = [
    "The", "ancient", "castle", "overlooks", "the", "quiet", "village",  # 0-6
    "Many", "tourists", "visit", "this", "remarkable", "place",          # 7-12
]
SENTS = [[0, 6], [7, 12]]


def _wj(words):
    return [
        {"w": w, "s": float(i), "e": float(i) + 0.5} for i, w in enumerate(words)
    ]


def _long_material():
    """5 x 7-word sentences; nouns spaced so >=3 blanks fit with 5-word gaps."""
    pattern = ["The", "little", "castle", "stands", "near", "the", "river"]
    words = []
    sents = []
    for k in range(5):
        words.extend(pattern)
        sents.append([k * 7, k * 7 + 6])
    return _wj(words), sents, words


class FakeChat:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, cfg, system, user, schema, client=None):
        self.calls.append({"system": system, "user": user, "schema": schema})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_llm_items_validated():
    wj = _wj(WORDS)
    items = [
        {"i0": 2, "i1": 2},  # valid (castle)
        {"i0": 99, "i1": 100},  # out of bounds
        {"i0": 4, "i1": 4, "answer": "rewritten"},  # rewritten answer
        {"i0": 3, "i1": 3},  # gap too small after word 2
        {"i0": 9, "i1": 9},  # valid (tourists)
    ]
    valid, rejected = validate_items(items, wj, SENTS)
    assert [v["i0"] for v in valid] == [2, 9]
    assert valid[0]["answer"] == "castle"
    assert len(rejected) == 3
    assert all(isinstance(r, str) and r for r in rejected)
    joined = " ".join(rejected)
    assert "越界" in joined
    assert "不一致" in joined or "改写" in joined
    assert "间距" in joined


def test_out_of_order_items_reordered():
    wj = _wj(WORDS)
    items = [{"i0": 9, "i1": 9}, {"i0": 2, "i1": 2}]
    valid, rejected = validate_items(items, wj, SENTS)
    assert [v["i0"] for v in valid] == [2, 9]
    assert rejected == []


def test_sentence_initial_and_span_and_confidence_rejected():
    wj = _wj(WORDS)
    wj[5]["p"] = 0.3
    items = [
        {"i0": 0, "i1": 0},  # sentence-initial
        {"i0": 5, "i1": 5},  # low confidence
        {"i0": 8, "i1": 12},  # span > 3 words
        {"i0": 11, "i1": 11},  # valid (remarkable)
    ]
    valid, rejected = validate_items(items, wj, SENTS)
    assert [v["i0"] for v in valid] == [11]
    assert len(rejected) == 3
    joined = " ".join(rejected)
    assert "句首" in joined and "置信度" in joined and "跨度" in joined


def test_word_limit_derive():
    assert derive_word_limit(1) == "ONE WORD ONLY"
    assert derive_word_limit(2) == "NO MORE THAN TWO WORDS"
    assert derive_word_limit(3) == "NO MORE THAN THREE WORDS"


@pytest.mark.asyncio
async def test_retry_once_with_rejection_reasons():
    wj = _wj(WORDS)
    chat = FakeChat(
        [
            {"items": [{"i0": 99, "i1": 100}]},  # all rejected
            {"items": [{"i0": 2, "i1": 2}, {"i0": 9, "i1": 9}]},
        ]
    )
    result = await generate_set(
        wj, SENTS, 2,
        llm_cfg={"provider": "zhipu", "api_key": "k"},
        chat_json_fn=chat,
    )
    assert len(chat.calls) == 2
    assert "99" in chat.calls[1]["user"]  # rejection reason carried
    assert "间距" in chat.calls[1]["user"] or "越界" in chat.calls[1]["user"]
    assert len(result.blanks) == 2
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_fallback_fills_shortfall():
    wj, sents, words = _long_material()
    chat = FakeChat([{"items": [{"i0": 2, "i1": 2}]}])  # 1 valid LLM item
    result = await generate_set(
        wj, sents, 4,
        llm_cfg={"provider": "zhipu", "api_key": "k"},
        chat_json_fn=chat,
    )
    assert len(result.blanks) == 4
    assert result.source == "llm"
    assert result.blanks[0].answer == "castle"
    starts = [b.word_start for b in result.blanks]
    assert len(set(starts)) == 4  # distinct, no overlap
    # global gap respected across the merged set
    for a, b in zip(result.blanks, result.blanks[1:]):
        assert b.word_start - a.word_end - 1 >= 5


@pytest.mark.asyncio
async def test_no_llm_pure_fallback():
    wj, sents, words = _long_material()
    chat = FakeChat([])
    result = await generate_set(wj, sents, 3, llm_cfg=None, chat_json_fn=chat)
    assert chat.calls == []  # LLM never contacted
    assert result.source == "fallback"
    assert len(result.blanks) == 3
    for b in result.blanks:
        assert b.answer in words
        assert b.word_limit


@pytest.mark.asyncio
async def test_llm_total_failure_falls_back():
    from app.services.llm import LlmError

    wj = _wj(WORDS)
    chat = FakeChat([LlmError("boom"), LlmError("boom")])
    result = await generate_set(
        wj, SENTS, 2,
        llm_cfg={"provider": "zhipu", "api_key": "k"},
        chat_json_fn=chat,
    )
    assert result.source == "fallback"
    assert len(result.blanks) == 2


def test_prompts_encode_current_item_rules():
    """The prompt must match the candidate pool and the name/spelling rule."""
    system = qg.SYSTEM_PROMPT
    # Names are only allowed when the audio spells them.
    assert "拼读" in system
    assert "未拼读的专有名词一律不要选" in system
    # The old, now-wrong advice must be gone.
    assert "数字与姓名适合" not in system
    # Hard exclusions the validator enforces.
    for phrase in ("开头两个词", "问候", "标签"):
        assert phrase in system
    assert "5 个词" in system

    words = [
        {"w": "The", "s": 0, "e": 0.1},
        {"w": "hotel", "s": 0.2, "e": 0.5},
        {"w": "near", "s": 0.6, "e": 0.8},
        {"w": "the", "s": 0.9, "e": 1.0},
        {"w": "railway", "s": 1.1, "e": 1.4},
        {"w": "station", "s": 1.5, "e": 1.8},
    ]
    candidates = [
        {"i0": 4, "i1": 5, "type": "noun", "score": 62},
        {"i0": 1, "i1": 1, "type": "noun", "score": 30},
    ]
    prompt = qg._user_prompt(words, 0, 5, candidates, 1)
    # Phrase spans are rendered with both bounds and their text.
    assert '4-5 "railway station" (noun)' in prompt
    assert '1 "hotel" (noun)' in prompt
    # Quota and the JSON contract stay explicit.
    assert "恰好 1 个" in prompt
    assert '"i0"' in prompt and '"i1"' in prompt


def test_candidate_hint_excludes_out_of_range_spans():
    words = [{"w": w, "s": 0, "e": 0} for w in "a b c d e".split()]
    candidates = [
        {"i0": 1, "i1": 2, "type": "noun", "score": 30},
        {"i0": 6, "i1": 7, "type": "noun", "score": 30},  # beyond range b=4
    ]
    hint = qg._candidate_hint(words, candidates, 0, 4)
    assert '1-2 "b c"' in hint
    assert "6-7" not in hint


@pytest.mark.asyncio
async def test_llm_picks_can_be_swapped_to_reach_quota(monkeypatch):
    """Accepted LLM picks may block every remaining candidate.

    Appending a pool candidate then cannot reach the requested count even
    though a different combination can. The final selection must be able to
    drop a pick to gain a slot instead of returning a short set.
    """
    words = [f"w{i}" for i in range(70)]
    wj = _wj(words)
    sents = [[0, len(words) - 1]]

    # Candidates: the LLM's five picks block three pool-only spans, but
    # 37 / 46-47 / 55-56 together with 17, 24-25 and 62 form a valid six.
    pool = [
        {"i0": 17, "i1": 17, "type": "noun", "score": 34},
        {"i0": 24, "i1": 25, "type": "noun", "score": 62},
        {"i0": 37, "i1": 37, "type": "noun", "score": 30},
        {"i0": 40, "i1": 41, "type": "noun", "score": 38},
        {"i0": 46, "i1": 47, "type": "noun", "score": 52},
        {"i0": 50, "i1": 51, "type": "noun", "score": 52},
        {"i0": 55, "i1": 56, "type": "number", "score": 103},
        {"i0": 62, "i1": 62, "type": "number", "score": 85},
    ]
    monkeypatch.setattr(
        qg.pos, "build_candidates", lambda *a, **k: [dict(c) for c in pool]
    )

    chat = FakeChat(
        [
            {
                "items": [
                    {"i0": 17, "i1": 17},
                    {"i0": 24, "i1": 25},
                    {"i0": 40, "i1": 41},
                    {"i0": 50, "i1": 51},
                    {"i0": 62, "i1": 62},
                ]
            }
        ]
    )
    result = await generate_set(
        wj, sents, 6,
        llm_cfg={"provider": "zhipu", "api_key": "k"},
        chat_json_fn=chat,
        tag_words_fn=lambda _w: [[] for _ in _w],
    )

    starts = [b.word_start for b in result.blanks]
    assert len(result.blanks) == 6, starts
    # The blocking picks (40-41 and 50-51) must have been swapped out.
    assert 40 not in starts and 50 not in starts
    # LLM picks that survived keep the set marked as LLM-sourced.
    assert result.source == "llm"
    for a, b in zip(result.blanks, result.blanks[1:]):
        assert b.word_start - a.word_end - 1 >= 5


@pytest.mark.asyncio
async def test_llm_picks_win_when_they_fit():
    words = "The little castle stands near the river".split()
    wj = _wj(words)
    sents = [[0, len(words) - 1]]
    chat = FakeChat([{"items": [{"i0": 2, "i1": 2}]}])
    result = await generate_set(
        wj, sents, 1,
        llm_cfg={"provider": "zhipu", "api_key": "k"},
        chat_json_fn=chat,
    )
    assert result.blanks[0].answer == "castle"
    assert result.source == "llm"


def test_fallback_prefers_higher_ranked_compatible_pair():
    candidates = [
        {"i0": 10, "i1": 10, "type": "noun"},  # rank 1, conflicts with #2/#3
        {"i0": 5, "i1": 5, "type": "noun"},    # rank 2, compatible with #3
        {"i0": 15, "i1": 15, "type": "noun"},  # rank 3, compatible with #2
    ]
    picked = qg.select_fallback(candidates, [], 2)
    assert [c["i0"] for c in picked] == [5, 15]


def test_fallback_respects_existing_blanks():
    candidates = [
        {"i0": 4, "i1": 4, "type": "noun"},
        {"i0": 5, "i1": 5, "type": "noun"},   # conflicts with the taken blank
        {"i0": 20, "i1": 20, "type": "noun"},
    ]
    picked = qg.select_fallback(candidates, [{"i0": 10, "i1": 10}], 2)
    assert [c["i0"] for c in picked] == [4, 20]


@pytest.mark.asyncio
async def test_fallback_does_not_drop_nouns_for_verbs():
    """Regression for the live demo: a verb must not displace a noun."""
    words = (
        "Good morning my name is Sarah and I would like to book a room "
        "for the weekend the hotel is located near the railway station "
        "and offers breakfast"
    ).split()
    wj = _wj(words)
    sents = [[0, len(words) - 1]]

    def fake_tags(_words):
        tags = [[] for _ in words]
        for i, w in enumerate(words):
            if w in ("morning", "name", "room", "weekend", "hotel",
                     "railway", "station", "breakfast"):
                tags[i] = ["NOUN"]
            elif w == "like":
                tags[i] = ["VERB"]
        return tags

    result = await generate_set(
        wj, sents, 3, llm_cfg=None, tag_words_fn=fake_tags
    )
    answers = {b.answer for b in result.blanks}
    assert "like" not in answers
    assert len(answers) == 3


@pytest.mark.asyncio
async def test_blank_fields_derived():
    wj = _wj(WORDS)
    chat = FakeChat([{"items": [{"i0": 2, "i1": 2, "type": "noun"}]}])
    result = await generate_set(
        wj, SENTS, 1,
        llm_cfg={"provider": "zhipu", "api_key": "k"},
        chat_json_fn=chat,
    )
    b = result.blanks[0]
    assert b.position == 1
    assert b.answer == "castle"
    assert b.word_start == 2 and b.word_end == 2
    assert b.t_start == 2.0 and b.t_end == 2.5
    assert b.type == "noun"
    assert b.word_limit == "ONE WORD ONLY"
    assert b.alternatives == []


@pytest.mark.asyncio
async def test_impossible_material_raises():
    # tiny material, no candidates, no LLM -> error rather than bad blanks
    wj = _wj(["Hi", "um"])
    with pytest.raises(QuestionGenError):
        await generate_set(wj, [[0, 1]], 5, llm_cfg=None)


@pytest.mark.asyncio
async def test_chunking_on_small_budget():
    # 24 words / 2 sentences; budget floored to MIN (4096) minus reserved
    # output tokens leaves a prompt budget far below one sentence-prompt,
    # so each sentence becomes its own independent stateless call.
    words = [f"w{i}" for i in range(24)]
    wj = _wj(words)
    sents = [[0, 11], [12, 23]]
    chat = FakeChat(
        [
            {"items": [{"i0": 3, "i1": 3}]},
            {"items": [{"i0": 15, "i1": 15}]},
        ]
    )
    result = await generate_set(
        wj, sents, 2,
        llm_cfg={"provider": "zhipu", "api_key": "k",
                 "max_context_tokens": 4096},
        chat_json_fn=chat,
        tag_words_fn=lambda ws: [[] for _ in ws],
    )
    assert len(chat.calls) == 2  # one per sentence chunk
    # chunk prompts are independent: each contains only its own range
    assert "0:" in chat.calls[0]["user"] and "12:" not in chat.calls[0]["user"]
    assert "12:" in chat.calls[1]["user"] and "11:" not in chat.calls[1]["user"]
    # no cross-call history: second prompt is not a continuation
    assert chat.calls[1]["user"].split("文本")[0] == chat.calls[0]["user"].split("文本")[0]
    # merged result enforces global constraints
    starts = sorted(b.word_start for b in result.blanks)
    assert starts == [3, 15]
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_merge_enforces_global_gap():
    # both chunks propose blanks near the boundary -> merge drops conflicts
    words = [f"w{i}" for i in range(24)]
    wj = _wj(words)
    sents = [[0, 11], [12, 23]]
    chat = FakeChat(
        [
            {"items": [{"i0": 10, "i1": 10}]},
            {"items": [{"i0": 12, "i1": 12}]},  # only 1 word gap across chunks
            {"items": [{"i0": 18, "i1": 18}]},
            {"items": [{"i0": 20, "i1": 20}]},
        ]
    )
    result = await generate_set(
        wj, sents, 2,
        llm_cfg={"provider": "zhipu", "api_key": "k",
                 "max_context_tokens": 4096},
        chat_json_fn=chat,
        tag_words_fn=lambda ws: [[] for _ in ws],
    )
    starts = [b.word_start for b in result.blanks]
    assert len(starts) == 2
    assert starts[1] - starts[0] - 1 >= 5
