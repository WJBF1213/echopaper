"""Answer grading with normalization (Task B4).

Normalization pipeline (spec §6.1 判分, Global Constraints):
NFKC -> lower -> keep only [a-z0-9-] plus CJK -> collapse whitespace.
Commas are removed so "3,000" == "3000"; apostrophes are removed so a
user typing "theyre" matches the answer "they're" (plan B4 test).
Pure stdlib; no framework imports (portable services layer).
"""
from __future__ import annotations

import re
import unicodedata

_KEEP_EXTRA = re.compile(r"[^a-z0-9\-\u4e00-\u9fff\u3400-\u4dbf]")
_WS = re.compile(r"\s+")


def normalize_answer(s: str) -> str:
    """Canonical form used on both the user input and the expected answer."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    # commas removed so 3,000 == 3000; apostrophes removed (theyre == they're)
    s = s.replace(",", "").replace("'", "")
    s = _KEEP_EXTRA.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def grade(user: str, answer: str, alternatives: list[str]) -> bool:
    """Exact match after normalization against answer or any alternative."""
    u = normalize_answer(user)
    if u == "":
        return False
    if u == normalize_answer(answer):
        return True
    return any(u == normalize_answer(alt) for alt in alternatives)
