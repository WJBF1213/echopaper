"""Candidate word selection for blank generation (Task B3).

Pure stdlib: spaCy is loaded lazily and its absence degrades to a
heuristic noun-majority pool (spec §6.1 step 1 + degradation path).
This module must stay free of any web-framework imports.
"""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WORDFREQ_FILE = DATA_DIR / "wordfreq_en.txt"

# spaCy-style POS -> candidate type
TAG_TO_TYPE = {
    "NOUN": "noun",
    "PROPN": "name",
    "NUM": "number",
    "ADJ": "adj",
    "VERB": "verb",
}
# ranking priority: nouns dominate real IELTS answers (~93%)
TYPE_RANK = {"noun": 0, "number": 1, "name": 2, "adj": 3, "verb": 4}

MIN_CONFIDENCE = 0.6

# Fallback function-word list when spaCy is unavailable (its STOP_WORDS
# is larger; this covers the pure function words).
_FALLBACK_STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those of to in on at by
    for with about into over after before between out against during without
    within along across behind beyond plus up down off above below is are was
    were be been being am do does did doing have has had having will would
    can could shall should may might must i you he she it we they me him her
    us them my your his its our their mine yours hers ours theirs there here
    when where why how what which who whom whose not no nor so too very just
    as from until while again further once
    """.split()
)

_nlp_cache: object | None = None
_nlp_tried = False
_freq_cache: frozenset[str] | None = None


def _get_nlp():
    """Lazily load en_core_web_sm; None when spaCy/model is unavailable."""
    global _nlp_cache, _nlp_tried
    if _nlp_tried:
        return _nlp_cache
    _nlp_tried = True
    try:  # pragma: no cover - exercised implicitly via tag_words tests
        import spacy

        _nlp_cache = spacy.load("en_core_web_sm")
    except Exception:
        _nlp_cache = None
    return _nlp_cache


def _freq() -> frozenset[str]:
    global _freq_cache
    if _freq_cache is None:
        try:
            text = WORDFREQ_FILE.read_text(encoding="utf-8")
            _freq_cache = frozenset(
                line.strip().lower() for line in text.splitlines() if line.strip()
            )
        except OSError:
            _freq_cache = frozenset()
    return _freq_cache


def _stopwords() -> frozenset[str]:
    try:
        from spacy.lang.en.stop_words import STOP_WORDS

        return frozenset(STOP_WORDS) | _FALLBACK_STOPWORDS
    except Exception:
        return _FALLBACK_STOPWORDS


def tag_words(words: list[str]) -> list[list[str]]:
    """POS-tag each word (list of tags per word; empty lists without spaCy).

    spaCy may tokenize a word into several tokens ("don't" -> do + n't);
    every token is assigned to the input word containing its char offset,
    so output length always equals input length.
    """
    nlp = _get_nlp()
    if nlp is None or not words:
        return [[] for _ in words]
    text = " ".join(words)
    offsets: list[int] = []
    pos = 0
    for w in words:
        offsets.append(pos)
        pos += len(w) + 1
    # word i covers [offsets[i], offsets[i]+len(words[i]))
    bounds = [offsets[i] + len(words[i]) for i in range(len(words))]

    result: list[list[str]] = [[] for _ in words]
    wi = 0
    for tok in nlp(text):
        idx = tok.idx
        while wi < len(words) - 1 and idx >= bounds[wi]:
            wi += 1
        if idx >= bounds[wi] and wi == len(words) - 1:
            continue  # token beyond last word (shouldn't happen)
        result[wi].append(tok.pos_)
    return result


def _heuristic_type(word: str, rare: bool) -> str | None:
    """Noun-majority heuristic used when POS tags are unavailable."""
    w = word.lower()
    if any(ch.isdigit() for ch in word):
        return "number"
    if word[0].isupper() and word[1:].islower():
        return "name"  # capitalised mid-text word (sentence-initial excluded)
    if len(w) >= 5 and rare:
        return "noun"
    if len(w) >= 6:
        return "noun"
    return None


def build_candidates(
    words_json: list[dict],
    sentences: list[list[int]],
    blank_count: int,
    tag_words_fn=None,
) -> list[dict]:
    """Build the ranked candidate pool (spec §6 step 1).

    Filters: confidence < 0.6, sentence-initial words, pure function words.
    Sort: candidate type (nouns first), rarity (outside 5k freq table),
    then word length. Capped at blank_count * 4 items.
    """
    tagger = tag_words_fn if tag_words_fn is not None else tag_words
    words = [w["w"] for w in words_json]
    tags = tagger(words)

    sentence_initial = {s for s, _e in sentences}
    freq = _freq()
    stops = _stopwords()

    pool: list[dict] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i in sentence_initial:
            continue
        if lower in stops:
            continue
        p = words_json[i].get("p")
        if p is not None and p < MIN_CONFIDENCE:
            continue
        rare = lower not in freq
        if tags and i < len(tags) and tags[i]:
            ctype = None
            for t in tags[i]:
                ctype = TAG_TO_TYPE.get(t)
                if ctype:
                    break
        else:
            ctype = _heuristic_type(word, rare)
        if ctype is None:
            continue
        pool.append({"i0": i, "i1": i, "type": ctype})

    pool.sort(
        key=lambda c: (
            TYPE_RANK[c["type"]],
            0 if words[c["i0"]].lower() not in freq else 1,
            -len(words[c["i0"]]),
            c["i0"],
        )
    )
    return pool[: max(0, blank_count * 4)]
