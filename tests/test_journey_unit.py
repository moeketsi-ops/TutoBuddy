"""The homework-week script: every problem is one code can mark, and the
scripted learner's answers get the verdicts the script says."""

import json
from pathlib import Path

import pytest

from app.tutor import answer_check
from app.tutor.rag import topic_hint

WEEK = json.loads((Path(__file__).resolve().parent.parent / "evals" / "journey" / "homework_week_g8.json").read_text())
PROBLEMS = [(d["day"], d["topic"], p) for d in WEEK["days"] for p in d["problems"]]
G8 = ["Area and Perimeter", "Surface Area and Volume", "Algebraic Equations", "Integers"]


@pytest.mark.parametrize("day,topic,prob", PROBLEMS, ids=lambda x: x["turns"][0][:30] if isinstance(x, dict) else str(x))
def test_scripted_turns_get_the_scripted_verdicts(day, topic, prob):
    problem = prob["turns"][0]
    assert answer_check.solve_problem(problem), problem
    for msg, truth in zip(prob["turns"][1:], prob["truth"][1:]):
        got = (answer_check.check(problem, msg) or {}).get("verdict")
        if truth == "correct":
            assert got == "correct", (problem, msg, got)
        elif truth == "wrong":
            assert got == "wrong", (problem, msg, got)


@pytest.mark.parametrize("day,topic,prob", PROBLEMS, ids=lambda x: x["turns"][0][:30] if isinstance(x, dict) else str(x))
def test_problems_land_on_the_days_topic(day, topic, prob):
    assert topic_hint(prob["turns"][0], G8) == topic


def test_every_problem_type_has_a_misconception():
    assert {p["type"] for _, _, p in PROBLEMS} <= set(WEEK["misconceptions"])


def test_ai_learner_prose_answers_are_read_by_their_final_number():
    from evals.journey.week import _verdict
    p = "How do I find the perimeter of a rectangle that is 8 cm by 3 cm?"
    assert _verdict(p, "i add 8+3=11 then again for the other two sides so the perimeter is 22 cm", ["22"]) == "correct"
    assert _verdict(p, "so 8 times 3 is 24 cm", ["22"]) == "wrong"
    assert _verdict("Convert 3 m² to cm²", "so it's 30 000 cm²", ["30000", "30 000"]) == "correct"
    assert _verdict(p, "i dont get it", ["22"]) is None


ALG = json.loads((Path(__file__).resolve().parent.parent / "evals" / "journey" / "homework_week_g8_algebra.json").read_text())
ALG_PROBLEMS = [p for d in ALG["days"] for p in d["problems"]]
_EXPECT = {"correct": "correct", "wrong": "wrong", "partial": "step_forward"}


@pytest.mark.parametrize("prob", ALG_PROBLEMS, ids=lambda p: p["turns"][0][:40])
def test_algebra_week_turns_get_the_scripted_verdicts(prob):
    problem = prob["turns"][0]
    solved = answer_check.solve_problem(problem)
    assert solved and solved["kind"] == "simplify", problem
    for msg, truth in zip(prob["turns"][1:], prob["truth"][1:]):
        got = (answer_check.check(problem, msg) or {}).get("verdict")
        if truth in _EXPECT:
            assert got == _EXPECT[truth], (problem, msg, got)


def test_bracket_simplify_marks_steps_not_just_answers():
    p = "Simplify 3x(4x + 5) - 4x(7x - 8)"
    v = lambda m: (answer_check.check(p, m) or {}).get("verdict")  # noqa: E731
    assert v("-16x^2 + 47x") == "correct"
    assert v("12x^2") == "step_forward"            # answering "what is 3x times 4x?"
    assert v("-28x^2 + 32x") == "step_forward"     # the second bracket done right
    assert v("12x^2 + 15x - 28x^2 - 32x") == "wrong"  # the minus not carried into the bracket
    assert v("3x(4x+5) - 4x(7x-8)") is None        # the problem echoed back


def test_ai_learner_expression_answers_in_prose():
    from evals.journey.week import _verdict
    p = "Simplify 3x(4x + 5) - 4x(7x - 8)"
    assert _verdict(p, "ok so the answer is -16x² + 47x", ["-16x^2 + 47x"]) == "correct"
    assert _verdict(p, "i dont know how to start", ["-16x^2 + 47x"]) is None
