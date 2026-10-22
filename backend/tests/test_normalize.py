"""Task B2 tests: ASR output normalization."""
from app.services.normalize import (
    build_words_segments,
    norm_word,
    sentence_text,
    words_to_text,
)


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


# ------------------------------------------------- sentence_text (spec §7.1)


def test_sentence_text_inclusive_endpoints():
    words = [{"w": t} for t in ["Hello", "there", "my", "old", "friend"]]
    # closed interval [1, 3] -- both endpoints included
    assert sentence_text(words, 1, 3) == "there my old"
    # full-range and sub-range never leak neighbouring words
    assert sentence_text(words, 0, 4) == "Hello there my old friend"
    assert sentence_text(words, 2, 2) == "my"


def test_sentence_text_one_word_sentence():
    words = [{"w": "Thanks"}, {"w": "Next"}, {"w": "one"}]
    # 1-word sentences (start == end) derive exactly that word
    assert sentence_text(words, 0, 0) == "Thanks"
    assert sentence_text(words, 2, 2) == "one"


def test_sentence_text_no_punctuation_added():
    # words_json is already punctuation-stripped at the edges; sentence_text
    # adds nothing -- no trailing period, no commas (spec §7.1)
    words = [{"w": "Hello"}, {"w": "there"}]
    assert sentence_text(words, 0, 1) == "Hello there"
    # words_to_text's display behaviour (period appended) deliberately
    # differs -- it serves the transcript field, not translation keys
    assert words_to_text(words, [[0, 1]]) == "Hello there."


def test_sentence_text_internal_punctuation_preserved_as_is():
    # ASR words may keep punctuation INSIDE the token; join passes it through
    words = [{"w": "don't"}, {"w": "well-known"}, {"w": "U.S.A."},
             {"w": "someone's"}]
    assert sentence_text(words, 0, 3) == "don't well-known U.S.A. someone's"


def test_sentence_text_matches_frontend_join_semantics():
    # frontend/src/lib/time.ts sentenceText:
    #   words.slice(start, end + 1).map(w => w.w).join(' ').trim()
    # -> space join then trim; empty/whitespace words must not leave
    #    leading/trailing whitespace at the range edges
    words = [{"w": ""}, {"w": "a"}, {"w": "b"}, {"w": " "}]
    # JS trim === Python strip: edge whitespace introduced by empty words is
    # dropped, so the derivation is stable even for hand-edited words_json
    assert sentence_text(words, 0, 3) == "a b"
    assert sentence_text(words, 1, 2) == "a b"


def test_sentence_text_accepts_plain_word_strings():
    # exam_gen / pos hold words as list[str]; same authoritative derivation
    assert sentence_text(["one", "two", "three"], 1, 2) == "two three"


def test_sentence_text_unifies_legacy_derivations():
    """Spec §7.1: the historical join styles all funnel through here."""
    words, sentences = build_words_segments(
        _raw([("Hello", 0.0, 0.1, None), ("there.", 0.1, 0.2, None)])
    )
    s, e = sentences[0]
    legacy_plain = " ".join(x["w"] for x in words[s : e + 1]).strip()
    legacy_full_join = words_to_text(words)  # join-everything style
    legacy_period = words_to_text(words, sentences)  # period-appended style
    assert sentence_text(words, s, e) == legacy_plain == legacy_full_join
    # the period-appended style stays a display-only derivation: it is NOT
    # a translation-key source anymore, so it must not equal the key text
    assert legacy_period == legacy_plain + "."
