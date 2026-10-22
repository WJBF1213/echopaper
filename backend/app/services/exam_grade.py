"""Server-side paper grading (redesign §5.2, Task 15).

The single grading implementation moved up from the frontend's local
PaperView logic (design §5.2 服务端判分规则, 单一实现):

- letter items (``option``: mcq_single, ``matching``: matching /
  map_labelling) -- exact equality after strip + uppercase.
- multi-answer items (``option_multi``: mcq_multi) -- set comparison:
  split into letters, deduplicate, sort; "A,C" == "C,A" == "C,A,A".
- span items (``completion`` / ``short_answer``) -- normalize both sides
  and compare against the answer AND every alternative (normalized).

Pure functions only: no DB, no IO, no framework imports (portable
services layer, like the rest of ``app.services``).

Normalization choices (documented, §5.2 判分规则):
- NFKC first so a Chinese IME's full-width Latin ("ｇｕａｒｄ") still
  matches; harmless for ordinary ASCII answers.
- lowercase + strip + collapse whitespace runs to one space -- exactly
  the old PaperView ``normalizeText``.
- hyphen 归一: spaces adjacent to a hyphen collapse ("well- known" /
  "well - known" -> "well-known"). A hyphen is NOT equivalent to a
  space ("well known" stays wrong unless listed as an alternative) --
  matching PaperView semantics, where only case/edges/whitespace-runs
  were folded; the design asks for hyphen *shape* normalization only.
- other punctuation is KEPT: span answers are verbatim transcript
  spans, so "3,000" must not collapse onto "3000" and "it's" must not
  collapse onto "its" (a deliberate difference from the old cloze
  grader, which stripped both).
"""
from __future__ import annotations

import re
import unicodedata

from app.services.exam_presets import QUESTION_TYPES

_WS = re.compile(r"\s+")
# Spaces hugging a hyphen fold onto the hyphen: "well - known" -> "well-known"
_HYPHEN_SPACES = re.compile(r"\s*-\s*")
# Letter answers split like PaperView's answerLetters: anything that is
# not A-H separates letters (commas, spaces, stray punctuation).
_NON_LETTER = re.compile(r"[^A-H]+")


def normalize_answer(s: str) -> str:
    """Canonical form for span answers; applied to user input, the stored
    answer, and each alternative alike. See module docstring for the
    deliberate choices (NFKC, hyphen shape, punctuation kept)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = _WS.sub(" ", s).strip()
    s = _HYPHEN_SPACES.sub("-", s)
    return s


def _letters(value: str | None) -> list[str]:
    """Sorted, de-duplicated letter list ("c,a,a" -> ["A", "C"])."""
    parts = _NON_LETTER.split((value or "").upper())
    return sorted({p for p in parts if p})


def _answer_kind(item: dict) -> str:
    """The answer kind of one item: the registry's answer_kind for the
    item's type, with PaperView's kindOfType fallback for unknown keys
    (defensive -- validators only emit registry types)."""
    type_key = item.get("type") or ""
    qtype = QUESTION_TYPES.get(type_key)
    if qtype is not None:
        return qtype.answer_kind
    if type_key == "mcq_multi":
        return "option_multi"
    if type_key == "mcq_single":
        return "option"
    if type_key == "matching" or type_key.endswith("_labelling"):
        return "matching"
    return "span"


def grade_item(item: dict, user_answer: str | None) -> bool:
    """Grade one stored paper item against the candidate's answer.

    ``user_answer`` None/empty (unanswered) is always wrong.
    """
    kind = _answer_kind(item)
    answer = (item.get("answer") or "").strip()
    given = (user_answer or "").strip()

    if kind == "option_multi":
        expected = _letters(answer)
        return bool(expected) and expected == _letters(given)

    if kind in ("option", "matching"):
        # Exact letter equality after strip + case folding (§5.2).
        return bool(answer) and given.upper() == answer.upper()

    # span: normalized equality against the answer or any alternative.
    normalized = normalize_answer(given)
    if not normalized:
        return False
    if normalized == normalize_answer(answer):
        return True
    return any(
        normalized == normalize_answer(alt)
        for alt in item.get("alternatives") or []
    )


def grade_paper(paper: dict, answers: dict[int, str]) -> list[dict]:
    """Grade every item of a stored paper (groups -> items, paper order).

    ``answers`` maps item number to the candidate's answer string. Items
    with no entry in ``answers`` grade wrong with ``user_answer`` None;
    entries matching no item number are ignored. Each result row is
    ``{item_number, item_type, user_answer, correct, expected}`` where
    ``expected`` is the stored answer verbatim (the display form; the
    frontend resolves letters to option text via the paper JSON).
    """
    results: list[dict] = []
    for group in paper.get("groups") or []:
        for item in group.get("items") or []:
            number = item.get("number")
            raw = answers.get(number)
            user_answer = None if raw is None else str(raw)
            results.append(
                {
                    "item_number": number,
                    "item_type": item.get("type"),
                    "user_answer": user_answer,
                    "correct": grade_item(item, user_answer),
                    "expected": (item.get("answer") or "").strip(),
                }
            )
    return results
