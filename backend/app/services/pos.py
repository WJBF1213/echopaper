"""Candidate word selection for blank generation (Task B3).

Pure stdlib: spaCy is loaded lazily and its absence degrades to a
heuristic noun-majority pool (spec §6.1 step 1 + degradation path).
This module must stay free of any web-framework imports.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import normalize

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


# ---------------------------------------------------------------- candidates

# Base score by answer type. Digits and proper names are the least guessable
# answers in listening tests, so they outrank plain nouns.
TYPE_SCORE = {"number": 45, "name": 40, "noun": 30, "adj": 10, "verb": 8}

# Candidates below this score are not worth a blank (e.g. a duplicated
# generic noun with no other signal).
MIN_SCORE = 20

# First N words of a sentence are never blanked: they anchor the sentence and
# are usually discourse markers or greetings.
HEAD_WORDS = 2

_COPULAS = frozenset({"is", "are", "was", "were", "'s", "\u2019s"})
_LABEL_SKIP = frozenset(
    """
    the a an this that these those my your his her its our their
    of in on at for with from by to
    """.split()
)

_GREETING_RE = re.compile(
    r"^(good\s+(morning|afternoon|evening)|hello|hi|hey|welcome|"
    r"nice\s+to\s+meet\s+you|how\s+are\s+you|how\s+do\s+you\s+do)\b",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    r"^(thank\s+you|thanks|cheers|bye|goodbye|see\s+you|"
    r"have\s+a\s+(nice|good)\s+day|you'?re\s+welcome)\b",
    re.IGNORECASE,
)


def _formulaic_words(words: list[str], ranges: list[tuple[int, int]]) -> set[int]:
    """Word indices belonging to greeting / sign-off formulas.

    Only the formula itself is dropped ("Good morning." loses both words),
    not any content that happens to follow it in the same sentence.
    """
    out: set[int] = set()
    for s, e in ranges:
        # authoritative sentence derivation (spec §7.1)
        text = normalize.sentence_text(words, s, e)
        match = _GREETING_RE.search(text) or _CLOSING_RE.search(text)
        if not match:
            continue
        prefix = match.group(0)
        # Do not swallow a whole long sentence that merely starts politely.
        if len(prefix.split()) >= (e - s + 1):
            continue
        for k in range(s, min(s + len(prefix.split()), e + 1)):
            out.add(k)
    return out


_SPELL_CUES = frozenset(
    """
    spell spells spelled spelt spelling letter letters character characters
    double capital hyphen dash apostrophe surname first name
    """.split()
)
_SPELL_SEPARATORS = frozenset(
    {
        "hyphen", "dash", "space", "apostrophe", "dot", "comma",
        "fullstop", "underscore", "slash",
    }
)

# ASR often renders spoken letter names as ordinary words ("see" for C).
# These are only accepted *inside* an established spelling run, never on
# their own, so common words cannot fabricate a spelling.
_LETTER_HOMOPHONES = {
    "ay": "a", "aye": "a", "bee": "b", "be": "b", "see": "c", "sea": "c",
    "dee": "d", "eff": "f", "gee": "g", "aitch": "h", "eye": "i", "jay": "j",
    "kay": "k", "ell": "l", "em": "m", "en": "n", "oh": "o", "pea": "p",
    "cue": "q", "queue": "q", "are": "r", "ess": "s", "tee": "t",
    "you": "u", "vee": "v", "ex": "x", "why": "y", "zed": "z", "zee": "z",
}

_HYPHENS = "-‐‑–—"


def _letter_of(token: str) -> str | None:
    low = token.lower().strip(".").replace("-", "")
    if len(low) == 1 and low.isalnum():
        return low
    return _LETTER_HOMOPHONES.get(low)


def _spelling_runs(words: list[str]) -> tuple[list[dict], set[int]]:
    """Detect letter-by-letter spellings in the transcript.

    Returns run records ``{text, i0, i1, alternatives}`` and the word
    indices that form those spellings (those raw tokens must not be blanked
    individually: "S-A-R-A-H" is one answer, not five). A run needs at
    least three letters and one of: a hyphenated group, a nearby spelling
    cue ("spell", "capital", "double"), or four plain single letters.
    """
    runs: list[dict] = []
    covered: set[int] = set()
    n = len(words)
    i = 0
    while i < n:
        start = i
        letters: list[str] = []
        strict = 0
        has_hyphen = False
        used: list[int] = []
        j = i
        while j < n:
            token = words[j]
            low = token.lower()
            if low in _SPELL_SEPARATORS:
                used.append(j)
                j += 1
                continue
            parts = [p for p in re.split(f"[{_HYPHENS}]", token) if p]
            if (
                len(parts) >= 2
                and all(len(p) == 1 and p.isalnum() for p in parts)
            ):
                letters.extend(p.lower() for p in parts)
                strict += len(parts)
                has_hyphen = True
                used.append(j)
                j += 1
                continue
            if len(token) == 1 and token.isalnum():
                letters.append(low)
                strict += 1
                used.append(j)
                j += 1
                continue
            if low == "double" and j + 1 < n:
                nxt = words[j + 1].lower()
                if nxt in ("you", "u"):
                    letters.extend(["w", "w"])
                    strict += 2
                    used.extend([j, j + 1])
                    j += 2
                    continue
                letter = _letter_of(nxt)
                if letter:
                    letters.extend([letter, letter])
                    strict += 2
                    used.extend([j, j + 1])
                    j += 2
                    continue
            if low in _LETTER_HOMOPHONES and strict >= 2:
                letters.append(_LETTER_HOMOPHONES[low])
                used.append(j)
                j += 1
                continue
            break

        length = len(letters)
        if length >= 3:
            cue = any(
                words[k].lower() in _SPELL_CUES
                for k in range(max(0, start - 10), min(n, j + 2))
            )
            if has_hyphen or cue or (strict == length and length >= 4):
                text = "".join(letters)
                # The candidate types the name, not the letters.
                display = text.upper() if any(c.isdigit() for c in text) else text.title()
                runs.append(
                    {
                        "text": text,
                        "answer": display,
                        "i0": used[0],
                        "i1": used[-1],
                        "alternatives": [text, text.upper(), text.title()],
                    }
                )
                covered.update(used)
        i = max(j, i + 1)
    return runs, covered


def _is_spelled(text: str, runs: list[dict]) -> bool:
    compact = "".join(ch for ch in text.lower() if ch.isalnum())
    if len(compact) < 3:
        return False
    for run in runs:
        spelled = run["text"]
        if compact == spelled or compact in spelled:
            return True
    return False


# Public aliases for downstream generators (exam_gen) that need the same
# fairness rules without rebuilding the detection logic.
def spelling_runs(words: list[str]) -> tuple[list[dict], set[int]]:
    """Detect spelled-out names; returns (runs, covered word indices)."""
    return _spelling_runs(words)


def is_spelled(text: str, runs: list[dict]) -> bool:
    return _is_spelled(text, runs)

_TEMPORAL = frozenset(
    """
    monday tuesday wednesday thursday friday saturday sunday
    january february march april may june july august september october
    november december
    """.split()
)


def _revealed_label_words(
    words: list[str],
    tags: list[list[str]],
    sent_of: list[int],
) -> set[int]:
    """Words that a following value gives away ("The postcode is GU7 4BX").

    Listening tests do not ask candidates to fill in a label when the value
    is sitting right next to it. The value itself (a number or a proper
    name) remains a good blank.
    """
    revealed: set[int] = set()
    n = len(words)
    for j, word in enumerate(words):
        if word.lower() not in _COPULAS:
            continue
        has_value = False
        for k in range(j + 1, min(j + 5, n)):
            if sent_of[k] != sent_of[j]:
                break
            kw = words[k]
            if any(ch.isdigit() for ch in kw) or "PROPN" in tags[k]:
                has_value = True
                break
        if not has_value:
            continue
        k = j - 1
        marked = 0
        while k >= 0 and marked < 2 and sent_of[k] == sent_of[j]:
            low = words[k].lower()
            if low in _LABEL_SKIP:
                k -= 1
                continue
            if not any(ch.isalnum() for ch in words[k]):
                break
            revealed.add(k)
            marked += 1
            k -= 1
    return revealed


def build_candidates(
    words_json: list[dict],
    sentences: list[list[int]],
    blank_count: int,
    tag_words_fn=None,
) -> list[dict]:
    """Build the ranked candidate pool (spec §6 step 1).

    Candidates are single words *and* 2-3 word noun phrases ("railway
    station", "GU7 4BX"). Filters: low ASR confidence, first two words of a
    sentence, greeting/sign-off formulas, label words whose value is
    revealed by a neighbouring copula, and **proper names that the audio
    never spells out** (a listener cannot know "Sarah" is not "Sara").
    Ranking rewards digits, spelled names, multi-word spans and rare words,
    and penalises single words predictable from a compound partner.
    """
    tagger = tag_words_fn if tag_words_fn is not None else tag_words
    words = [w["w"] for w in words_json]
    n = len(words)
    if n == 0:
        return []
    tags = tagger(words)
    freq = _freq()
    stops = _stopwords()
    spelled_runs, spelling_words = _spelling_runs(words)

    ranges: list[tuple[int, int]] = []
    covered = -1
    for s, e in sentences:
        s = max(int(s), covered + 1)
        e = min(int(e), n - 1)
        if e < s:
            continue
        ranges.append((s, e))
        covered = e
    if covered < n - 1:
        ranges.append((covered + 1, n - 1))
    if not ranges:
        ranges = [(0, n - 1)]

    sent_of = [0] * n
    for si, (s, e) in enumerate(ranges):
        for i in range(s, e + 1):
            sent_of[i] = si
    sentence_start = [s for s, _e in ranges]
    formulaic = _formulaic_words(words, ranges)
    revealed = _revealed_label_words(words, tags, sent_of)

    def tag_of(i: int) -> list[str]:
        return tags[i] if i < len(tags) and tags[i] else []

    def type_of(i: int) -> str | None:
        if words[i].lower() in _TEMPORAL:
            return "noun"  # weekdays/months: temporal nouns, not spellable names
        for t in tag_of(i):
            ctype = TAG_TO_TYPE.get(t)
            if ctype:
                return ctype
        return _heuristic_type(words[i], words[i].lower() not in freq)

    def ok_word(i: int) -> bool:
        if not any(ch.isalnum() for ch in words[i]):
            return False
        if words[i].lower() in stops:
            return False
        if i in spelling_words:
            return False  # raw letter tokens of a spelled-out answer
        p = words_json[i].get("p")
        return not (p is not None and p < MIN_CONFIDENCE)

    def in_head_position(i: int) -> bool:
        return i >= sentence_start[sent_of[i]] + HEAD_WORDS

    def is_compound_partner(i: int) -> bool:
        return any(
            t in ("NOUN", "PROPN", "NUM") for t in tag_of(i)
        )

    def repeated(word: str) -> bool:
        low = word.lower()
        return sum(1 for w in words if w.lower() == low) > 1

    def score_span(i0: int, i1: int, ctype: str) -> int:
        span = words[i0 : i1 + 1]
        joined = "".join(span)
        score = TYPE_SCORE.get(ctype, 0)
        if any(ch.isdigit() for ch in joined):
            score += 30
        span_len = i1 - i0 + 1
        if span_len >= 2:
            score += 18 + 3 * (span_len - 2)
        if ctype == "name":
            # A spelled name is a fair listening item; an unspelled one is
            # guesswork ("Sarah"/"Sara", "Guildford"/"Guildforde").
            if _is_spelled(" ".join(span), spelled_runs):
                score += 20
            else:
                score -= 60
        if any(w.lower() not in freq for w in span):
            score += 10
        if max(len(w) for w in span) >= 7:
            score += 4
        if any(repeated(w) for w in span):
            score -= 10
        if span_len == 1:
            # A single word sitting next to a noun is usually the modifiable
            # half of a compound ("railway station", "parking space"): the
            # listener can guess it. Prefer blanking the whole phrase.
            for nb in (i0 - 1, i1 + 1):
                if 0 <= nb < n and ok_word(nb) and is_compound_partner(nb):
                    score -= 18
                    break
            # An adjective is likewise predictable from the noun it modifies.
            if ctype == "adj" and i1 + 1 < n and is_compound_partner(i1 + 1):
                score -= 18
        return score

    pool: list[dict] = []
    seen: set[tuple[int, int]] = set()

    def add(
        i0: int,
        i1: int,
        ctype: str,
        alternatives: list[str] | None = None,
        word_limit: str | None = None,
        answer: str | None = None,
    ) -> None:
        if (i0, i1) in seen:
            return
        seen.add((i0, i1))
        item = {
            "i0": i0,
            "i1": i1,
            "type": ctype,
            "score": score_span(i0, i1, ctype),
        }
        if alternatives:
            item["alternatives"] = alternatives
        if word_limit:
            item["word_limit"] = word_limit
        if answer:
            item["answer"] = answer
        pool.append(item)

    # Single-word candidates.
    for i in range(n):
        if not ok_word(i) or not in_head_position(i):
            continue
        if i in formulaic or i in revealed:
            continue
        ctype = type_of(i)
        if ctype is None:
            continue
        add(i, i, ctype)

    # Multi-word noun phrases / number groups. Tags are required because the
    # heuristic fallback cannot tell a compound from a verb phrase.
    if tags and any(tags):
        for i0 in range(n):
            for span_len in (2, 3):
                i1 = i0 + span_len - 1
                if i1 >= n or sent_of[i1] != sent_of[i0]:
                    continue
                if not in_head_position(i0):
                    continue
                if any(k in formulaic for k in range(i0, i1 + 1)):
                    continue
                if any(i in revealed for i in range(i0, i1 + 1)):
                    continue
                if not all(ok_word(k) for k in range(i0, i1 + 1)):
                    continue
                head_tags = tag_of(i1)
                head_type = next(
                    (TAG_TO_TYPE[t] for t in head_tags if t in TAG_TO_TYPE),
                    None,
                )
                if head_type not in ("noun", "name", "number"):
                    continue
                lead_ok = True
                for k in range(i0, i1):
                    if not any(
                        t in ("ADJ", "NOUN", "PROPN", "NUM") for t in tag_of(k)
                    ):
                        lead_ok = False
                        break
                if not lead_ok:
                    continue
                if any(ch.isdigit() for ch in "".join(words[i0 : i1 + 1])):
                    ctype = "number"
                elif all("PROPN" in tag_of(k) for k in range(i0, i1 + 1)):
                    ctype = "name"
                else:
                    ctype = "noun"
                add(i0, i1, ctype)

    # Spelled-out names are the one case where a proper name is a fair
    # listening item: the audio tells the candidate exactly how to write it.
    for run in spelled_runs:
        i0, i1 = run["i0"], run["i1"]
        if not ok_word(i0) and any(
            not any(ch.isalnum() for ch in words[k]) for k in range(i0, i1 + 1)
        ):
            continue
        add(
            i0,
            i1,
            "name",
            alternatives=run["alternatives"],
            word_limit="ONE WORD ONLY",
            answer=run["answer"],
        )

    pool = [c for c in pool if c["score"] >= MIN_SCORE]

    # Unspelled proper names never survive, not even as part of a phrase
    # that mixed a name with a common noun.
    pool = [
        c
        for c in pool
        if not (
            c["type"] == "name"
            and not _is_spelled(
                " ".join(words[c["i0"] : c["i1"] + 1]), spelled_runs
            )
        )
    ]

    # A phrase candidate subsumes its own words: blanking "railway" alone
    # while "station" stays visible is exactly the guessable pattern we are
    # trying to avoid. Drop the single-word versions of accepted phrases.
    phrase_spans = [
        (c["i0"], c["i1"]) for c in pool if c["i1"] > c["i0"]
    ]
    if phrase_spans:
        pool = [
            c
            for c in pool
            if c["i1"] > c["i0"]
            or not any(a <= c["i0"] <= b for a, b in phrase_spans)
        ]

    pool.sort(key=lambda c: (-c["score"], c["i0"], c["i1"]))
    return pool[: max(0, blank_count * 4)]
