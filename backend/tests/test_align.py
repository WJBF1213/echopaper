"""Task B8 tests: official-transcript to ASR word alignment (spec §6.1)."""
from app.services.align import align_transcript, should_use_aligned


def _asr(words, start=0.0, step=1.0, p=None):
    return [
        {
            "w": w,
            "s": start + i * step,
            "e": start + i * step + step / 2,
            **({"p": p} if p is not None else {}),
        }
        for i, w in enumerate(words)
    ]


def test_identical_texts_full_rate():
    asr = _asr(["hello", "there", "friend"], start=10.0)
    words, rate = align_transcript(["hello", "there", "friend"], asr)
    assert rate == 1.0
    assert [w["w"] for w in words] == ["hello", "there", "friend"]
    assert words[0]["s"] == 10.0
    assert words[2]["e"] == 12.5


def test_asr_error_word_gets_official_spelling():
    asr = _asr(["hello", "ther", "friend"], start=5.0)
    words, rate = align_transcript(["hello", "there", "friend"], asr)
    assert [w["w"] for w in words] == ["hello", "there", "friend"]
    # official spelling, ASR timestamps carried over the replace block
    assert words[1]["s"] == 6.0
    # 2 of 3 words matched exactly; replace word still got a timestamp
    assert rate >= 0.6
    assert should_use_aligned(rate)


def test_inserted_word_interpolated_p05():
    # official has one word ASR missed ("very" between known words)
    asr = _asr(["hello", "big", "castle"], start=0.0, step=2.0)
    words, rate = align_transcript(["hello", "very", "big", "castle"], asr)
    assert [w["w"] for w in words] == ["hello", "very", "big", "castle"]
    ins = words[1]
    assert ins["p"] == 0.5
    # interpolated between hello.e and big.s (may touch the boundary)
    assert ins["s"] > words[0]["e"]
    assert ins["e"] <= words[2]["s"]
    assert ins["s"] <= ins["e"]


def test_asr_extra_words_dropped():
    asr = _asr(["hello", "um", "uh", "castle"])
    words, rate = align_transcript(["hello", "castle"], asr)
    assert [w["w"] for w in words] == ["hello", "castle"]
    assert words[0]["s"] == 0.0
    assert words[1]["s"] == 3.0  # from asr word index 3


def test_case_and_punctuation_insensitive_match():
    asr = _asr(["hello", "there"])
    words, rate = align_transcript(["Hello,", "There."], asr)
    assert rate == 1.0
    assert [w["w"] for w in words] == ["Hello", "There"]
    assert words[0]["s"] == 0.0


def test_low_rate_flag():
    assert should_use_aligned(0.5) is False
    assert should_use_aligned(0.59) is False
    assert should_use_aligned(0.6) is True
    assert should_use_aligned(0.9) is True


def test_mostly_different_low_rate():
    asr = _asr(["alpha", "bravo", "charlie", "delta", "echo"])
    words, rate = align_transcript(["one", "two", "three", "four", "five"], asr)
    assert rate < 0.6
    assert should_use_aligned(rate) is False


def test_empty_inputs_safe():
    words, rate = align_transcript([], [])
    assert words == [] and rate == 0.0


def test_leading_and_trailing_inserts():
    asr = _asr(["middle"], start=5.0)
    words, rate = align_transcript(["the", "middle", "end"], asr)
    assert [w["w"] for w in words] == ["the", "middle", "end"]
    assert words[0]["p"] == 0.5
    assert words[2]["p"] == 0.5
    assert words[1]["s"] == 5.0
