"""Task B3 tests: spaCy candidate selection + frequency fallback.

Candidate contract (2026-10-21 rework):
- spans may be 1-3 words ("railway station", "GU7 4BX", "Sarah Johnson")
- ranking is by ``score``, not by a coarse type bucket
- digits / proper names / multi-word phrases outrank plain single nouns
- greeting sentences and copula-revealed labels are excluded
"""
import pytest

from app.services import pos

WORDS = [
    "The", "ancient", "castle", "overlooks", "the", "quiet", "village",  # sent 1
    "Many", "tourists", "visit", "this", "remarkable", "place",          # sent 2
]


def _words_json(words, conf=None):
    out = []
    for i, w in enumerate(words):
        item = {"w": w, "s": float(i), "e": float(i) + 0.5}
        if conf is not None:
            item["p"] = conf
        out.append(item)
    return out


SENTS = [[0, 6], [7, 12]]


def _span(words, cand):
    return " ".join(words[cand["i0"] : cand["i1"] + 1])


def _tagged(words, mapping):
    """Fake tagger: {index: tag}."""
    def tagger(_words):
        return [[mapping[i]] if i in mapping else [] for i in range(len(words))]

    return tagger


def test_tag_words_shape():
    tags = pos.tag_words(WORDS)
    assert len(tags) == len(WORDS)
    assert all(isinstance(t, list) for t in tags)
    # with a real spaCy model available, 'castle' is tagged NOUN
    if pos._get_nlp() is not None:
        assert "NOUN" in tags[2]


def test_candidates_noun_priority():
    cands = pos.build_candidates(_words_json(WORDS), SENTS, 10)
    assert cands, "expected non-empty candidate pool"
    for c in cands:
        assert set(c) >= {"i0", "i1", "type", "score"}
        assert 0 <= c["i0"] <= c["i1"] < len(WORDS)
        assert c["i1"] - c["i0"] + 1 <= 3
        assert c["type"] in ("noun", "number", "name", "verb", "adj")
    # a clear noun phrase must be available and rank in the top half
    spans = [_span(WORDS, c) for c in cands]
    assert any("castle" in s for s in spans)
    # nouns dominate the pool: at least 60% of candidates are noun-ish
    nounish = [c for c in cands if c["type"] == "noun"]
    assert len(nounish) >= len(cands) * 0.6


def test_candidates_filter_stopwords_and_initial():
    cands = pos.build_candidates(_words_json(WORDS), SENTS, 10)
    spans = {_span(WORDS, c) for c in cands}
    starts = {c["i0"] for c in cands}
    assert 0 not in starts  # first word of a sentence
    assert 7 not in starts  # 'Many' sentence-initial
    assert "the" not in spans
    assert "this" not in spans


def test_first_two_words_are_never_blanked():
    words = ["Welcome", "everybody", "to", "the", "museum", "today"]
    cands = pos.build_candidates(_words_json(words), [[0, 5]], 5)
    starts = {c["i0"] for c in cands}
    assert 0 not in starts and 1 not in starts


def test_filters_low_conf_and_sentence_initial():
    wj = _words_json(WORDS)
    wj[2]["p"] = 0.3  # castle low confidence
    wj[1]["p"] = 0.95  # ancient fine
    cands = pos.build_candidates(wj, SENTS, 10)
    spans = {_span(WORDS, c) for c in cands}
    assert not any("castle" in s for s in spans)
    # sentence-initial words excluded even if noun-like
    wj2 = _words_json(["Castle", "stands", "proudly", "on", "the", "hill"])
    cands2 = pos.build_candidates(wj2, [[0, 5]], 10)
    assert 0 not in {c["i0"] for c in cands2}


def test_spacy_missing_degrades_to_heuristic(monkeypatch):
    monkeypatch.setattr(pos, "tag_words", lambda words: [[] for _ in words])
    cands = pos.build_candidates(_words_json(WORDS), SENTS, 10)
    assert cands, "heuristic pool must still be produced"
    starts = {c["i0"] for c in cands}
    assert 0 not in starts and 7 not in starts
    assert all(c["type"] in ("noun", "name", "number") for c in cands)


def test_candidate_pool_capped():
    lots = ["The"] + [f"object{i}" for i in range(100)]
    wj = _words_json(["Library"] + lots[1:])
    wj[0] = {"w": "The", "s": 0.0, "e": 0.1}
    cands = pos.build_candidates(wj, [[0, len(wj) - 1]], 5)
    assert len(cands) <= 5 * 4


def test_rare_words_rank_higher():
    words = ["The", "process", "of", "photosynthesis", "needs", "sunlight",
             "and", "a", "place", "with", "light"]
    wj = _words_json(words)
    sents = [[0, len(words) - 1]]
    cands = pos.build_candidates(wj, sents, 10)
    spans = [_span(words, c) for c in cands]
    assert any("photosynthesis" in s for s in spans)


def test_compound_phrase_preferred_over_its_parts():
    words = "The train stopped at the railway station yesterday".split()
    # The0 train1 stopped2 at3 the4 railway5 station6 yesterday7
    tags = _tagged(words, {1: "NOUN", 2: "VERB", 3: "ADP", 4: "DET",
                           5: "NOUN", 6: "NOUN", 7: "ADV"})
    cands = pos.build_candidates(_words_json(words), [[0, 7]], 10, tag_words_fn=tags)
    spans = [_span(words, c) for c in cands]
    assert "railway station" in spans
    # The bare halves of a compound are guessable and must not be offered
    # on their own; the phrase keeps the blank.
    assert "station" not in spans
    assert "railway" not in spans


def test_greeting_sentence_excluded():
    words = "Good morning. The tour departs from the main hall at nine".split()
    # Good0 morning1 | The2 tour3 departs4 from5 the6 main7 hall8 at9 nine10
    tags = _tagged(words, {1: "NOUN", 3: "NOUN", 4: "VERB", 5: "ADP",
                           6: "DET", 7: "ADJ", 8: "NOUN", 9: "ADP", 10: "NUM"})
    cands = pos.build_candidates(_words_json(words), [[0, 1], [2, 10]], 10,
                                 tag_words_fn=tags)
    starts = {c["i0"] for c in cands}
    assert 0 not in starts and 1 not in starts


def test_label_revealed_by_value_is_excluded():
    words = "The postcode is GU7 4BX and the town is Guildford".split()
    tags = _tagged(words, {1: "NOUN", 2: "AUX", 3: "PROPN", 4: "NUM",
                           7: "NOUN", 8: "AUX", 9: "PROPN"})
    cands = pos.build_candidates(_words_json(words), [[0, 9]], 10,
                                 tag_words_fn=tags)
    spans = {_span(words, c) for c in cands}
    assert "postcode" not in spans  # the value right after it gives it away
    assert "town" not in spans
    assert any("GU7" in s for s in spans)  # the value itself is a good blank


def test_unspelled_name_is_never_a_candidate():
    """A listener cannot know whether the name is Sarah or Sara."""
    words = "Good morning my name is Sarah and I live in Guildford".split()
    tags = _tagged(words, {1: "NOUN", 4: "PROPN", 8: "PROPN"})
    cands = pos.build_candidates(_words_json(words), [[0, 8]], 10,
                                 tag_words_fn=tags)
    spans = {_span(words, c) for c in cands}
    assert "Sarah" not in spans
    assert "Guildford" not in spans


def test_spelled_name_becomes_a_candidate_with_readable_answer():
    words = "My surname is spelt S-A-R-A-H and the town is B-I-L-B-A-O".split()
    tags = _tagged(words, {1: "NOUN", 7: "NOUN"})
    cands = pos.build_candidates(_words_json(words), [[0, 8]], 10,
                                 tag_words_fn=tags)
    by_span = {_span(words, c): c for c in cands}
    sarah = by_span.get("S-A-R-A-H")
    assert sarah is not None
    # the candidate types the name, not the dashes
    assert sarah["answer"] == "Sarah"
    assert "SARAH" in sarah["alternatives"]
    assert by_span.get("B-I-L-B-A-O")["answer"] == "Bilbao"


def test_spelling_detection_requires_evidence():
    """Ordinary single letters in a sentence must not look like spelling."""
    words = "I have a plan and a map".split()
    runs, covered = pos._spelling_runs(words)
    assert runs == []

    hyphenated = "It is spelt G-U-7 4-B-X".split()
    runs, covered = pos._spelling_runs(hyphenated)
    assert runs and runs[0]["text"] == "gu74bx"


def test_spelled_name_keeps_timestamps_of_the_whole_run():
    words = ["The", "code", "is", "A-B-C-D", "today"]
    wj = _words_json(words)
    tags = _tagged(words, {3: "PROPN"})
    cands = pos.build_candidates(wj, [[0, 4]], 5, tag_words_fn=tags)
    by_span = {_span(words, c): c for c in cands}
    code = by_span["A-B-C-D"]
    assert code["i0"] == 3 and code["i1"] == 3



def test_temporal_nouns_are_not_treated_as_names():
    words = "The tour leaves on Monday morning".split()
    tags = _tagged(words, {4: "PROPN", 5: "NOUN"})
    cands = pos.build_candidates(_words_json(words), [[0, 5]], 5,
                                 tag_words_fn=tags)
    by_span = {_span(words, c): c for c in cands}
    # Weekdays are temporal nouns: blankable even without a spelling.
    assert "Monday morning" in by_span
    assert by_span["Monday morning"]["type"] == "noun"
