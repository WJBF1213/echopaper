"""Server-side paper grading tests (design §5.2, Task 15).

``app.services.exam_grade`` holds the pure grading functions moved up
from the frontend's local PaperView grading: letter items are exact
equalty, multi-answer items compare as sorted sets, span items compare
after normalization against the answer and every alternative.

The old blanks-world ``app.services.grading`` is untouched here (it
serves the legacy sets flow until that world is deleted); this module
covers only the new paper semantics.
"""
from __future__ import annotations

from app.services.exam_grade import grade_item, grade_paper, normalize_answer


# --------------------------------------------------------- normalize_answer


def test_normalize_case_and_edges():
    assert normalize_answer("  Passport ") == "passport"
    assert normalize_answer("BANK  Statement") == "bank statement"
    assert normalize_answer("MAIN HALL") == "main hall"


def test_normalize_collapses_whitespace_runs():
    assert normalize_answer("gift   shop") == "gift shop"
    assert normalize_answer("two  hundred and   fifty") == (
        "two hundred and fifty"
    )
    # Tabs/newlines fold to a single space too.
    assert normalize_answer("bus\tstop\njust\toutside") == (
        "bus stop just outside"
    )


def test_normalize_full_width_nfkc():
    # A Chinese IME easily produces full-width Latin; NFKC folds it.
    assert normalize_answer("Ｇｕａｒd") == "guard"
    assert normalize_answer("ｗｅｌｌ－ｋｎｏｗｎ") == "well-known"


def test_normalize_hyphen_spaces():
    assert normalize_answer("well- known") == "well-known"
    assert normalize_answer("well -known") == "well-known"
    assert normalize_answer("well - known") == "well-known"
    assert normalize_answer("well-  known") == "well-known"
    assert normalize_answer("e-mail") == "e-mail"


def test_normalize_hyphen_is_not_a_space():
    """Documented choice: hyphen shape is normalized (stray spaces around
    it collapse) but a hyphen never equals a space -- "well known" stays
    wrong against the answer "well-known", matching PaperView semantics
    where only case/edges/whitespace-runs were folded."""
    assert normalize_answer("well known") != normalize_answer("well-known")


def test_normalize_keeps_other_punctuation():
    """Span answers are verbatim transcript spans: numbers and possessives
    must NOT collapse (a deliberate difference from the old blanks
    grading, which stripped commas and apostrophes)."""
    assert normalize_answer("3,000") != normalize_answer("3000")
    assert normalize_answer("it's") != normalize_answer("its")


def test_normalize_empty():
    assert normalize_answer("") == ""
    assert normalize_answer("   ") == ""


# ------------------------------------------------------------- grade_item


def _item(type_: str, answer: str, alternatives: list[str] | None = None):
    return {
        "number": 1,
        "type": type_,
        "stem": "...",
        "answer": answer,
        "alternatives": alternatives or [],
    }


def test_option_letter_exact_after_case_and_strip():
    assert grade_item(_item("mcq_single", "B"), "b")
    assert grade_item(_item("mcq_single", "B"), "  B  ")
    assert not grade_item(_item("mcq_single", "B"), "A")
    assert not grade_item(_item("mcq_single", "B"), "")  # unanswered
    assert not grade_item(_item("mcq_single", "B"), None)
    assert not grade_item(_item("mcq_single", "B"), "AB")  # not a letter


def test_matching_letter_exact_equality():
    # matching + map_labelling: one letter from the shared option pool.
    assert grade_item(_item("matching", "C"), "c")
    assert grade_item(_item("map_labelling", "D"), " D ")
    assert not grade_item(_item("matching", "C"), "D")


def test_option_multi_set_comparison():
    assert grade_item(_item("mcq_multi", "A,C"), "C,A")  # order-insensitive
    assert grade_item(_item("mcq_multi", "A,C"), "a, c")
    assert grade_item(_item("mcq_multi", "A,C"), " A ,C ")  # stray spaces
    assert grade_item(_item("mcq_multi", "A,C"), "C,A,A")  # dupes collapse
    assert not grade_item(_item("mcq_multi", "A,C"), "A")  # too few
    assert not grade_item(_item("mcq_multi", "A,C"), "A,B,C")  # too many
    assert not grade_item(_item("mcq_multi", "A,C"), "A,D")
    assert not grade_item(_item("mcq_multi", "A,C"), "")  # unanswered
    assert not grade_item(_item("mcq_multi", "A,C"), None)
    # Single-answer multi edge: one expected letter, one given.
    assert grade_item(_item("mcq_multi", "B"), "B")


def test_span_normalizes_both_sides():
    item = _item("completion", "Passport", alternatives=["travel documents"])
    assert grade_item(item, "passport")
    assert grade_item(item, "  PASSPORT  ")
    assert grade_item(item, "Travel   Documents")  # alternative, ws-collapsed
    assert not grade_item(item, "passports")
    assert not grade_item(item, "")
    assert not grade_item(item, None)


def test_span_hyphen_alternatives():
    item = _item("short_answer", "well-known", alternatives=["well known"])
    assert grade_item(item, "Well-Known")
    assert grade_item(item, "well- known")  # hyphen shape normalized
    assert grade_item(item, "well known")  # explicit alternative


def test_span_full_width_user_input():
    assert grade_item(_item("completion", "guard"), "ＧＵＡＲＤ")


# ------------------------------------------------------------- grade_paper


def _paper(items: list[dict]) -> dict:
    return {"total_items": len(items), "groups": [{"type": "mixed", "items": items}]}


def test_grade_paper_covers_every_item_in_order():
    paper = _paper([
        {"number": 1, "type": "mcq_single", "answer": "B"},
        {"number": 2, "type": "mcq_multi", "answer": "A,C"},
        {"number": 3, "type": "completion", "answer": "passport"},
        {"number": 4, "type": "matching", "answer": "D"},
    ])
    results = grade_paper(paper, {1: "b", 2: "C,A", 3: " Passport "})
    assert [r["item_number"] for r in results] == [1, 2, 3, 4]
    assert [r["item_type"] for r in results] == [
        "mcq_single", "mcq_multi", "completion", "matching",
    ]
    assert [r["correct"] for r in results] == [True, True, True, False]
    # expected is the stored answer, displayed as-is.
    assert [r["expected"] for r in results] == ["B", "A,C", "passport", "D"]
    assert [r["user_answer"] for r in results] == [
        "b", "C,A", " Passport ", None,
    ]


def test_grade_paper_missing_answer_is_wrong():
    paper = _paper([{"number": 7, "type": "completion", "answer": "cafe"}])
    results = grade_paper(paper, {})
    assert results == [{
        "item_number": 7,
        "item_type": "completion",
        "user_answer": None,
        "correct": False,
        "expected": "cafe",
    }]


def test_grade_paper_ignores_unknown_item_numbers():
    paper = _paper([{"number": 1, "type": "mcq_single", "answer": "A"}])
    results = grade_paper(paper, {99: "B"})
    assert len(results) == 1
    assert results[0]["user_answer"] is None
    assert results[0]["correct"] is False


def test_grade_paper_walks_all_groups():
    paper = {"groups": [
        {"type": "mcq_single", "items": [{"number": 1, "type": "mcq_single",
                                          "answer": "A"}]},
        {"type": "completion", "items": [{"number": 2, "type": "completion",
                                          "answer": "cafe"}]},
    ]}
    results = grade_paper(paper, {1: "A", 2: "CAFE"})
    assert [r["correct"] for r in results] == [True, True]
