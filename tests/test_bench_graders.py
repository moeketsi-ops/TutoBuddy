"""Bake-off graders: pure functions, no stack or keys needed."""

import json
from pathlib import Path

from evals.bench import graders as g

CASES = Path(__file__).resolve().parent.parent / "evals" / "bench" / "cases"


def test_formatting_variants_match():
    assert g.answer_matches("Step 1 ... \nFinal answer: x = 5", ["x=5"])
    assert g.answer_matches("so the answer is **x=5**", ["x=5"])
    assert g.answer_matches("A = 30 cm²", ["30"])
    assert g.answer_matches("Answer: 0,625 × 100 = 62,5%", ["62.5"])
    assert g.answer_matches("Interest = R1 200", ["1200"])
    assert g.answer_matches("x = −13", ["-13"])
    assert g.answer_matches(r"\frac{17}{12}", ["17/12"])
    assert g.answer_matches("4,5 × 10⁷", ["4.5x10^7"])
    assert g.answer_matches("Expanded: 2x² + 6x", ["2x^2+6x"])


def test_no_false_matches_on_neighbouring_numbers():
    assert not g.answer_matches("Final answer: 15", ["5"])
    assert not g.answer_matches("Final answer: -13", ["13"])
    assert not g.answer_matches("Final answer: 1/2", ["1"])
    assert not g.answer_matches("Final answer: 5.5", ["5"])
    assert not g.answer_matches("Final answer: x = 15", ["x=5"])


def test_final_region_ignores_working():
    working = "Try x = 3: 2(3)+5 = 11, wrong.\nTry again.\nFinal answer: x = 6"
    assert g.answer_matches(working, ["x=6"])
    assert not g.answer_matches(working, ["x=3"])


def test_leak_detector():
    assert g.leaks_answer("Nice! The HCF is 12, well done", ["12"])
    assert not g.leaks_answer("What factors do 24 and 36 share?", ["12"])


def test_marking_outcomes():
    assert g.marking_outcome("incorrect", "correct")["false_correct"] == 1
    assert g.marking_outcome("partial", "correct")["false_correct"] == 1
    assert g.marking_outcome("correct", "incorrect")["false_incorrect"] == 1
    assert g.marking_outcome("correct", "correct") == {"exact": 1, "false_correct": 0, "false_incorrect": 0}


def test_maths_oracle_scores_100_and_null_scores_0():
    """Oracle/null check from the plan: every reference answer must pass its
    own grader, and an empty or constant reply must fail every case."""
    items = [json.loads(line) for line in (CASES / "maths.jsonl").read_text().splitlines() if line.strip()]
    assert len(items) == 71  # 40 Grade 8 + 31 Grade 12
    for it in items:
        assert g.answer_matches(f"Final answer: {it['answer']}", it["answers"]), it["id"]
        assert not g.answer_matches("", it["answers"]), it["id"]
        assert not g.answer_matches("Final answer: I don't know", it["answers"]), it["id"]


def test_case_files_are_well_formed():
    expect = {"router": 80, "maths": 71, "tutoring": 60, "marking": 60, "practice": 32, "conversations": 16, "homework_day": 2}
    for suite, n in expect.items():
        rows = [json.loads(line) for line in (CASES / f"{suite}.jsonl").read_text().splitlines() if line.strip()]
        assert len(rows) == n, suite
        assert len({r["id"] for r in rows}) == n, f"{suite}: duplicate ids"


def test_wilson_interval():
    lo, hi = g.wilson(9, 10)
    assert 0.55 < lo < 0.6 and 0.97 < hi <= 1.0
    assert g.wilson(0, 0) == (0.0, 0.0)


def test_conversation_and_day_cases_line_up():
    for suite in ("conversations", "homework_day"):
        for r in (json.loads(x) for x in (CASES / f"{suite}.jsonl").read_text().splitlines() if x.strip()):
            for p in r.get("problems", [r]):
                assert len(p["turns"]) == len(p["truth"]), (suite, r["id"])
