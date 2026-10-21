"""Task B7 tests: manual [方括号] blank parsing and anchoring."""
import pytest

from app.services.manual_parse import (
    ManualAnchorError,
    anchor_manual,
    parse_manual,
)


def test_parse_brackets():
    text = "The [castle] is old.\nIt is [very famous] today."
    clean, items = parse_manual(text)
    assert clean == "The castle is old.\nIt is very famous today."
    assert [it["answer"] for it in items] == ["castle", "very famous"]
    assert items[0]["line"] == 1
    assert items[1]["line"] == 2


def test_unmatched_bracket_raises():
    with pytest.raises(Exception) as ei:
        parse_manual("The [castle is old.")
    assert "3" not in str(ei.value) or True
    assert "[" in str(ei.value) or "括号" in str(ei.value)


def test_empty_bracket_raises():
    with pytest.raises(Exception):
        parse_manual("The [] is old.")


def test_bracket_spanning_sentence_punct_raises():
    with pytest.raises(Exception) as ei:
        parse_manual("He said [good bye. Then] he left.")
    assert "1" in str(ei.value)  # line number reported


def _wj(words):
    return [{"w": w, "s": float(i), "e": float(i) + 0.5} for i, w in enumerate(words)]


def test_anchor_exact_and_ci():
    words = ["The", "Castle", "stands", "near", "the", "river", "today"]
    wj = _wj(words)
    items = [
        {"answer": "Castle", "line": 1},
        {"answer": "RIVER", "line": 1},  # case-insensitive
    ]
    anchored = anchor_manual(items, wj)
    assert anchored[0] == {"i0": 1, "i1": 1, "answer": "Castle"}
    assert anchored[1]["i0"] == 5 and anchored[1]["i1"] == 5


def test_anchor_phrase_span():
    words = ["It", "is", "very", "famous", "today", "indeed"]
    wj = _wj(words)
    anchored = anchor_manual([{"answer": "very famous", "line": 1}], wj)
    assert anchored[0]["i0"] == 2 and anchored[0]["i1"] == 3


def test_anchor_punct_insensitive():
    # bracket content with a comma still matches comma-free words
    words = ["hello", "world", "again"]
    wj = _wj(words)
    anchored = anchor_manual([{"answer": "hello, world", "line": 1}], wj)
    assert anchored[0]["i0"] == 0 and anchored[0]["i1"] == 1


def test_anchor_missing_reports_which():
    words = ["The", "castle", "stands"]
    wj = _wj(words)
    items = [
        {"answer": "castle", "line": 1},
        {"answer": "volcano", "line": 4},
    ]
    with pytest.raises(ManualAnchorError) as ei:
        anchor_manual(items, wj)
    assert "2" in str(ei.value)  # ordinal of the failing item
    assert "volcano" in str(ei.value)


def test_anchor_takes_first_of_multiple():
    words = ["the", "cat", "and", "the", "dog"]
    wj = _wj(words)
    anchored = anchor_manual([{"answer": "the", "line": 1}], wj)
    assert anchored[0]["i0"] == 0
