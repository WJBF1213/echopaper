"""Manual [方括号] blank parsing and word anchoring (Task B7).

parse_manual strips brackets from raw transcript text and returns the
answers (with source line numbers); anchor_manual maps each answer onto
consecutive word indices in words_json via case/punctuation-insensitive
comparison. Bracket content spanning sentence punctuation, unclosed
brackets, empty brackets, and answers with no verbatim match all raise
errors carrying the offending line/ordinal.
"""
from __future__ import annotations

from app.services.grading import normalize_answer

MAX_ANCHOR_SPAN = 6  # words searched when anchoring one bracket answer
# punctuation that must not appear inside a bracket answer
SPAN_FORBIDDEN = ".?!;:"


class ManualError(Exception):
    """Parse-stage error (unclosed/empty/punct-spanning bracket)."""


class ManualAnchorError(ManualError):
    """An answer could not be anchored verbatim into words_json."""


def parse_manual(text: str) -> tuple[str, list[dict]]:
    """Return (bracket-free text, [{'answer', 'line'}])."""
    items: list[dict] = []
    out: list[str] = []
    i = 0
    line = 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            out.append(ch)
            i += 1
            continue
        if ch == "[":
            end = text.find("]", i + 1)
            if end == -1:
                raise ManualError(f"第 {line} 行：方括号未闭合")
            answer = text[i + 1 : end].strip()
            if not answer:
                raise ManualError(f"第 {line} 行：空的方括号 []")
            if any(c in answer for c in SPAN_FORBIDDEN):
                raise ManualError(
                    f"第 {line} 行：括号内容 “{answer}” 跨越句读标点，"
                    "请在句子内部标记"
                )
            items.append({"answer": answer, "line": line})
            out.append(answer)
            # account for newlines inside the bracket content
            line += answer.count("\n")
            i = end + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), items


def anchor_manual(items: list[dict], words_json: list[dict]) -> list[dict]:
    """Anchor each parsed answer to a contiguous word-index span.

    Matching is case- and punctuation-insensitive (grading normalization);
    the first occurrence in word order wins.
    """
    words = [w["w"] for w in words_json]
    lowered = [normalize_answer(w) for w in words]
    result: list[dict] = []
    for ordinal, item in enumerate(items, start=1):
        answer = item["answer"]
        target = normalize_answer(answer)
        found = None
        if target:
            for i0 in range(len(words)):
                acc = ""
                for i1 in range(i0, min(i0 + MAX_ANCHOR_SPAN, len(words))):
                    acc = (acc + " " + lowered[i1]).strip()
                    if acc == target:
                        found = (i0, i1)
                        break
                    if len(acc) > len(target):
                        break
                if found:
                    break
        if found is None:
            raise ManualAnchorError(
                f"第 {ordinal} 个括号（第 {item.get('line', '?')} 行）"
                f"的答案 “{answer}” 无法在转写中找到逐字匹配"
            )
        result.append({"i0": found[0], "i1": found[1], "answer": answer})
    return result
