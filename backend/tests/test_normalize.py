"""Task B2 tests: ASR output normalization."""
from app.services.normalize import build_words_segments, norm_word, words_to_text


def _raw(words_with_ts):
    """Build raw word dicts; items are (text, start, end, p_or_None)."""
    return [
        {"w": t, "s": s, "e": e, **({"p": p} if p is not None else {})}
        for (t, s, e, p) in words_with_ts
    ]


def test_punctuation_stripped():
    assert norm_word("hello,") == "hello"
    assert norm_word("\"quoted\"") == "quoted"
    assert norm_word("(yes)") == "yes"
    assert norm_word("don't") == "don't"  # internal apostrophe kept
    assert norm_word("well-known") == "well-known"  # internal hyphen kept
    assert norm_word("...") == ""
    assert norm_word("Mr.") == "Mr"


def test_sentence_split_on_punct():
    raw = _raw(
        [("Hello", 0.0, 0.3, None), ("there.", 0.3, 0.6, None),
         ("How", 0.6, 0.8, None), ("are", 0.8, 1.0, None),
         ("you?", 1.0, 1.3, 0.97)]
    )
    words, sentences = build_words_segments(raw)
    assert [x["w"] for x in words] == ["Hello", "there", "How", "are", "you"]
    assert sentences == [[0, 1], [2, 4]]
    # timestamps + confidence passthrough
    assert words[0]["s"] == 0.0 and words[0]["e"] == 0.3
    assert words[4]["p"] == 0.97
    assert "p" not in words[0]


def test_long_sentence_split_at_comma():
    # 30 words, single sentence, commas inside
    items = []
    t = 0.0
    for i in range(30):
        text = "word%d," % i if i in (10, 20) else "word%d" % i
        if i == 29:
            text = "word29."
        items.append((text, t, t + 0.1, None))
        t += 0.1
    words, sentences = build_words_segments(items and _raw(items))
    assert len(words) == 30
    assert len(sentences) >= 2
    # full coverage, no gaps/overlaps
    assert sentences[0][0] == 0
    assert sentences[-1][1] == len(words) - 1
    for (_, e1), (s2, _) in zip(sentences, sentences[1:]):
        assert s2 == e1 + 1
    # each resulting sentence within the 25-word cap
    assert all(e - s + 1 <= 25 for s, e in sentences)


def test_pure_punctuation_tokens_dropped():
    raw = _raw([("um", 0.0, 0.2, None), (".", 0.2, 0.25, None), ("Next", 0.25, 0.5, None)])
    words, sentences = build_words_segments(raw)
    # "." token produces no word but still closes its sentence
    assert [x["w"] for x in words] == ["um", "Next"]
    assert sentences == [[0, 0], [1, 1]]


def test_words_to_text_roundtrip():
    raw = _raw(
        [("Hello", 0.0, 0.2, None), ("there.", 0.2, 0.4, None),
         ("How", 0.4, 0.6, None), ("are", 0.6, 0.8, None),
         ("you?", 0.8, 1.0, None)]
    )
    words, sentences = build_words_segments(raw)
    text = words_to_text(words, sentences)
    assert text.endswith(".")
    # re-lex: whitespace tokens with dummy timestamps
    re_raw = [
        {"w": tok, "s": 0.0, "e": 0.1} for tok in text.split()
    ]
    words2, sentences2 = build_words_segments(re_raw)
    assert [x["w"] for x in words2] == [x["w"] for x in words]
    assert sentences2 == sentences


def test_words_to_text_without_sentences():
    words = [{"w": "one", "s": 0, "e": 1}, {"w": "two", "s": 1, "e": 2}]
    assert words_to_text(words) == "one two"
