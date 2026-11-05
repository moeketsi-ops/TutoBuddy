"""Sign-up check-in logic (app/tutor/diagnostic.py), pure functions only."""

import pytest

from app.tutor import diagnostic as d


def _run(grade, pick):
    """Answer every item with pick(item) and return the finished state."""
    st = d.start(grade)
    while not d.finished(st):
        d.answer(st, pick(d.current(st)))
    return st


def test_every_topic_once_when_all_right():
    st = _run(8, lambda it: it["answer"])
    assert len(st["answers"]) == 22                     # core items only
    res = d.results(st)
    assert res["first_try"] == 22 and res["score_pct"] == 80.0
    assert d.focus(res) == []


def test_a_miss_brings_the_easier_item_next():
    st = d.start(12)
    first = d.current(st)
    d.answer(st, "?")
    nxt = d.current(st)
    assert nxt["topic"] == first["topic"] and nxt["kind"] == "easier"


def test_scores_and_misconceptions():
    def pick(it):
        if it["topic"] == "Integers":                   # both Integers items wrong, with sign errors
            return next(l for l, c in it["misc"].items() if c == "SIGN_ERR")
        if it["topic"] == "Exponents":                  # core wrong, easier right
            return it["answer"] if it["kind"] == "easier" else "?"
        return it["answer"]
    res = d.results(_run(8, pick))
    assert res["topics"]["Integers"] == {"score": 20.0, "level": "none",
                                         "misc": ["SIGN_ERR", "SIGN_ERR"]}
    assert res["topics"]["Exponents"]["score"] == 50.0
    assert d.focus(res) == ["Integers", "Exponents"]
    msg = d.report("Thabo", 8, res, d.focus(res))
    assert "signs with negative numbers" in msg and "we start with Integers" in msg


def test_focus_prefers_heavier_topics_among_equals():
    res = {"topics": {"A": {"score": 20.0, "level": "none", "misc": []},
                      "B": {"score": 20.0, "level": "none", "misc": []},
                      "C": {"score": 50.0, "level": "easier", "misc": []}}}
    assert d.focus(res, {"A": 5, "B": 9}) == ["B", "A", "C"]


@pytest.mark.parametrize("text,expected", [
    ("a", "A"), ("B", "B"), ("(c)", "C"), ("d)", "D"), ("Option b", "B"), ("?", "?"),
    ("I don't know", "?"), ("not sure", "?"), ("12", "B"),            # option text "12"
    ("How do I factorise?", None), ("hi", None), ("x = 5 or so", None),
])
def test_parse_answer(text, expected):
    item = {"options": ["6", "12", "72", "4"]}
    assert d.parse_answer(text, item) == expected


def test_question_text_numbers_topics_not_items():
    st = d.start(10)
    assert "Check-in 1/13" in d.question_text(st)
    d.answer(st, "?")                                   # easier item next: no new number
    assert "one more on this" in d.question_text(st)
    d.answer(st, "?")
    assert "Check-in 2/13" in d.question_text(st)


def test_no_bank_for_grade_9():
    assert not d.available(9) and d.available(8) and d.available(12)
