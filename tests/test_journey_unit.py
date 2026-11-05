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
