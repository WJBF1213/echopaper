"""ASR output normalization (Task B2).

Engines emit raw word dicts ``{"w","s","e","p"?}`` where ``w`` may carry
attached punctuation (``"hello,"``). This module strips punctuation while
preserving the original casing, passes timestamps/confidence through, and
derives sentence boundaries as closed word-index ranges ``[start, end]``.
"""
from __future__ import annotations

import string

# Chars stripped from word edges. Internal apostrophes/hyphens are preserved.
_EDGE_PUNCT = set(string.punctuation) - {"'", "-"}

SENTENCE_END = ".?!"
LONG_SENTENCE = 25


def norm_word(w: str) -> str:
    """Strip leading/trailing punctuation, keep internal ' and -."""
    return w.strip("".join(sorted(_EDGE_PUNCT)))


def _strip_quotes(w: str) -> str:
    return w.strip("\"'")


def _kind(raw_w: str) -> tuple[str, str]:
    """Classify a raw token -> (sentence_end_char|None, is_comma)."""
    core = _strip_quotes(raw_w)
    if core and core[-1] in SENTENCE_END:
        return core[-1], False
    if core and core[-1] == ",":
        return None, True
    return None, False


def build_words_segments(
    raw_words: list[dict],
) -> tuple[list[dict], list[list[int]]]:
    """Normalize raw engine words into words_json + sentence ranges.

    - Punctuation stripped from word edges; empty results dropped.
    - Sentence ends detected from trailing . ? ! on the RAW token
      (punctuation-only tokens also close a sentence).
    - Sentences longer than LONG_SENTENCE words are split at the comma
      nearest the middle (recursively) so chunks stay readable.
    """
    words: list[dict] = []
    keep_map: dict[int, int] = {}  # raw idx -> kept idx
    for ri, raw in enumerate(raw_words):
        text = norm_word(str(raw.get("w", "")))
        if text == "":
            continue
        keep_map[ri] = len(words)
        item: dict = {
            "w": text,
            "s": float(raw.get("s", 0.0)),
            "e": float(raw.get("e", 0.0)),
        }
        if raw.get("p") is not None:
            item["p"] = float(raw["p"])
        words.append(item)

    # per-raw-token kind + nearest kept index at-or-before each raw token
    raw_kinds = [_kind(str(raw.get("w", ""))) for raw in raw_words]
    prev_kept: list[int] = []
    last = -1
    for ri in range(len(raw_words)):
        if ri in keep_map:
            last = keep_map[ri]
        prev_kept.append(last)

    # comma-terminated words, as kept indices (from RAW trailing commas)
    kept_commas = [
        keep_map[ri]
        for ri, (_end, comma) in enumerate(raw_kinds)
        if comma and ri in keep_map
    ]

    # First pass: sentence ranges from .?! boundaries on raw tokens.
    sentences: list[list[int]] = []
    cur_start = 0
    for ri, (end_char, _comma) in enumerate(raw_kinds):
        if end_char is None and ri != len(raw_words) - 1:
            continue
        end_kept = prev_kept[ri]
        if end_kept < cur_start:
            continue  # stray punctuation with no words in this sentence
        sentences.append([cur_start, end_kept])
        cur_start = end_kept + 1

    # Second pass: split overlong sentences at commas.
    result: list[list[int]] = []
    for s, e in sentences:
        result.extend(_split_long(s, e, kept_commas))
    return words, result


def _split_long(start: int, end: int, commas: list[int]) -> list[list[int]]:
    """Split [start,end] at commas so no chunk exceeds LONG_SENTENCE."""
    length = end - start + 1
    if length <= LONG_SENTENCE:
        return [[start, end]]
    inside = [i for i in commas if start <= i < end]
    if not inside:
        return [[start, end]]
    mid = (start + end) // 2
    cut = min(inside, key=lambda i: abs(i - mid))
    return _split_long(start, cut, commas) + _split_long(cut + 1, end, commas)


def words_to_text(words: list[dict], sentences: list[list[int]] | None = None) -> str:
    """Rebuild readable text: spaces between words, no space before '. '."""
    if sentences is None:
        return " ".join(x["w"] for x in words)
    ends = {e for _, e in sentences}
    parts: list[str] = []
    for i, w in enumerate(words):
        token = w["w"]
        if i in ends:
            token += "."
        parts.append(token)
    return " ".join(parts)
