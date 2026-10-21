"""Task B3 tests: spaCy candidate selection + frequency fallback."""
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
    # shape
    for c in cands:
        assert set(c) >= {"i0", "i1", "type"}
        assert c["i1"] == c["i0"]
        assert c["type"] in ("noun", "number", "name", "verb", "adj")
    # nouns rank ahead of adjectives/verbs
    types = [c["type"] for c in cands]
    first_non_noun = next(
        (i for i, t in enumerate(types) if t not in ("noun",)), len(types)
    )
    assert all(t == "noun" for t in types[:first_non_noun])
    assert "noun" in types
    # a clear noun like 'castle'/'village'/'tourists' must be in the pool
    words_by_idx = {c["i0"]: c for c in cands}
    assert 2 in words_by_idx  # castle


def test_candidates_filter_stopwords_and_initial():
    cands = pos.build_candidates(_words_json(WORDS), SENTS, 10)
    idxs = {c["i0"] for c in cands}
    assert 0 not in idxs  # 'The' sentence-initial + stopword
    assert 7 not in idxs  # 'Many' sentence-initial
    assert 4 not in idxs  # 'the' stopword
    assert 10 not in idxs  # 'this' stopword


def test_filters_low_conf_and_sentence_initial():
    wj = _words_json(WORDS)
    wj[2]["p"] = 0.3  # castle low confidence
    wj[1]["p"] = 0.95  # ancient fine
    cands = pos.build_candidates(wj, SENTS, 10)
    idxs = {c["i0"] for c in cands}
    assert 2 not in idxs  # low-confidence word excluded
    # sentence-initial words excluded even if noun-like
    wj2 = _words_json(["Castle", "stands", "proudly", "on", "the", "hill"])
    idxs2 = {c["i0"] for c in pos.build_candidates(wj2, [[0, 5]], 10)}
    assert 0 not in idxs2


def test_spacy_missing_degrades_to_heuristic(monkeypatch):
    monkeypatch.setattr(pos, "tag_words", lambda words: [[] for _ in words])
    cands = pos.build_candidates(_words_json(WORDS), SENTS, 10)
    assert cands, "heuristic pool must still be produced"
    # stopwords and sentence-initial still filtered
    idxs = {c["i0"] for c in cands}
    assert 0 not in idxs and 4 not in idxs and 7 not in idxs and 10 not in idxs
    assert all(c["type"] in ("noun", "name", "number") for c in cands)


def test_candidate_pool_capped():
    lots = ["The"] + [
        f"object{i}" for i in range(100)
    ]
    wj = _words_json(["Library"] + lots[1:])
    wj[0] = {"w": "The", "s": 0.0, "e": 0.1}
    # single long sentence starting at index 0
    cands = pos.build_candidates(wj, [[0, len(wj) - 1]], 5)
    assert len(cands) <= 5 * 4


def test_rare_words_rank_higher():
    # 'photosynthesis' (rare) vs 'place' (in freq table): both nouns,
    # rare one should come first in the pool.
    words = ["The", "process", "of", "photosynthesis", "needs", "sunlight",
             "and", "a", "place", "with", "light"]
    wj = _words_json(words)
    sents = [[0, len(words) - 1]]
    cands = pos.build_candidates(wj, sents, 10)
    by_idx = {c["i0"]: i for i, c in enumerate(cands)}
    if 3 in by_idx and 8 in by_idx:
        assert by_idx[3] < by_idx[8]
