"""Task B4 tests: grading normalization (spec §6.1 判分)."""
import pytest

from app.services.grading import grade, normalize_answer


def test_case_punct_width():
    assert normalize_answer("3,000") == normalize_answer("3000")
    assert grade("3,000", "3000", [])
    assert normalize_answer("Ｇｕａｒd") == "guard"  # full-width NFKC
    assert normalize_answer("They're") == normalize_answer("theyre")
    assert normalize_answer("  Hello   World!  ") == "hello world"
    assert normalize_answer("e-mail") == "e-mail"  # hyphen kept
    assert normalize_answer("it's") == "its"


def test_case_insensitive():
    assert grade("LIBRARY", "library", [])
    assert grade("Library", "library", [])


def test_alternatives():
    assert grade("3", "three", ["three", "3"])
    assert grade("three", "3", ["three"])
    assert not grade("thirty", "3", ["three"])


def test_empty_user_fails():
    assert not grade("", "answer", [])
    assert not grade("   ", "answer", [])
    assert not grade("...", "answer", [])


def test_cjk_preserved():
    # CJK kept through normalization (interface zh, materials en, but robust)
    assert normalize_answer("你好") == "你好"
    assert grade("你好", "你好", [])


def test_wrong_answer_fails():
    assert not grade("castle", "village", [])
    assert not grade("castles", "castle", [])  # no stemming
