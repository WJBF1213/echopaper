"""Official transcript to ASR word-level alignment (Task B8, spec §6.1).

The pasted official transcript is the authoritative text; ASR provides
timestamps. difflib.SequenceMatcher aligns normalized word sequences:
equal/replace blocks map ASR timestamps onto official words, inserted
official words (ASR misses) get interpolated times and low confidence
p=0.5, ASR-only words are dropped. Match rate < 0.6 -> caller should
keep the raw ASR words instead.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from app.services.normalize import norm_word

MATCH_RATE_THRESHOLD = 0.6
INSERT_CONFIDENCE = 0.5
FALLBACK_STEP = 0.05  # seconds used when no neighbour bounds an insert

_KEEP_EXTRA = re.compile(r"[^a-z0-9\-\u4e00-\u9fff\u3400-\u4dbf]")
_WS = re.compile(r"\s+")


def normalize_answer(s: str) -> str:
    """Word-level canonical form used on both the official and the ASR
    side of the alignment (moved here from the deleted blanks-world
    ``grading.py`` in Task 18): NFKC -> lower -> drop commas/apostrophes
    ("theyre" matches "they're", "3,000" matches "3000") -> keep only
    [a-z0-9-] plus CJK -> collapse whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = s.replace(",", "").replace("'", "")
    s = _KEEP_EXTRA.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def should_use_aligned(rate: float) -> bool:
    return rate >= MATCH_RATE_THRESHOLD


def align_transcript(
    official_words: list[str],
    asr_words_json: list[dict],
) -> tuple[list[dict], float]:
    """Align official words to ASR words -> (new words_json, match rate)."""
    if not official_words or not asr_words_json:
        return [], 0.0

    off_raw = [str(w) for w in official_words]
    off_norm = [normalize_answer(w) for w in off_raw]
    asr_norm = [normalize_answer(w["w"]) for w in asr_words_json]

    sm = difflib.SequenceMatcher(None, off_norm, asr_norm, autojunk=False)
    opcodes = sm.get_opcodes()

    # pass 1: which official indices got a timestamp from which asr index
    ts: dict[int, tuple[float, float, float | None]] = {}  # off idx -> (s,e,p)
    matched = 0  # only textually EQUAL words count toward the match rate
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                a = asr_words_json[j1 + k]
                ts[i1 + k] = (
                    float(a.get("s", 0.0)),
                    float(a.get("e", 0.0)),
                    a.get("p"),
                )
            matched += i2 - i1
        elif tag == "replace":
            off_len = max(1, i2 - i1)
            asr_len = max(1, j2 - j1)
            for k in range(i2 - i1):
                # proportional position inside the ASR replacement block
                j = j1 + min(asr_len - 1, round(k * asr_len / off_len))
                a = asr_words_json[j]
                ts[i1 + k] = (
                    float(a.get("s", 0.0)),
                    float(a.get("e", 0.0)),
                    a.get("p"),
                )

    # pass 2: build words_json; interpolate timestamps for inserted words
    rate = matched / len(off_raw)

    out: list[dict] = []
    for i, raw in enumerate(off_raw):
        item = {"w": norm_word(raw)}
        if not item["w"]:
            item["w"] = raw.strip() or "?"
        if i in ts:
            s, e, p = ts[i]
            item["s"], item["e"] = s, e
            if p is not None:
                item["p"] = float(p)
        else:
            item["p"] = INSERT_CONFIDENCE  # placeholder time fixed below
        out.append(item)

    _interpolate_inserts(out, ts)

    return out, rate


def _interpolate_inserts(
    out: list[dict], ts: dict[int, tuple[float, float, float | None]]
) -> None:
    """Give inserted (untimed) words times between their mapped neighbours."""
    n = len(out)
    i = 0
    while i < n:
        if i in ts:
            i += 1
            continue
        j = i
        while j < n and j not in ts:
            j += 1
        prev_e = out[i - 1]["e"] if i > 0 else None
        next_s = out[j]["s"] if j < n else None
        count = j - i
        if prev_e is not None and next_s is not None and next_s > prev_e:
            step = (next_s - prev_e) / (count + 1)
            for k in range(count):
                start = prev_e + step * (k + 1)
                out[i + k]["s"] = round(start, 3)
                out[i + k]["e"] = round(min(start + step, next_s), 3)
        else:
            base = prev_e if prev_e is not None else max(
                0.0, (next_s if next_s is not None else 0.0) - count * FALLBACK_STEP
            )
            for k in range(count):
                out[i + k]["s"] = round(base + k * FALLBACK_STEP, 3)
                out[i + k]["e"] = round(base + (k + 1) * FALLBACK_STEP, 3)
        i = j
