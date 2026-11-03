"""Unit tests for the fixes from the 31 Oct bake-off (pure functions: no
database, Redis or model). Each case is a learner message from a bench
transcript where the model's own label, or its reply, was wrong."""

import pytest

from app.tutor import answer_check
from app.tutor.engine import strip_greeting
from app.tutor.rag import topic_hint

INT = "What is -8 + 3?"
FRAC = "How do I add 1/3 and 1/6?"
SQ = "What is 3 squared?"
SIMP = "How do I simplify 3a + 2b + 5a?"
AREA = "How do I find the area of a rectangle that is 7 cm by 4 cm?"
DERIV = "How do I find the derivative of f(x) = x^3 - 6x?"
SUM = "What is the sum to infinity of 16 + 8 + 4 + ...?"
LOG = "Solve log2(x) = 5"


# ── Code checks more than equations now ──────────────────────────────────────

@pytest.mark.parametrize("problem,reply,verdict", [
    # c04: Claude Haiku labelled the learner's correct -5 as wrong
    (INT, "11", "wrong"), (INT, "-11", "wrong"), (INT, "-5", "correct"), (INT, "−5", "correct"),
    (INT, "-8 + 3", None),                       # the problem typed back is no answer
    (FRAC, "2/9", "wrong"), (FRAC, "1/3 is 2/6", "step_forward"),
    (FRAC, "3/6 which is 1/2", "correct"), (FRAC, "1/2", "correct"),
    (SQ, "6", "wrong"), (SQ, "9", "correct"),
    (AREA, "11", "wrong"), (AREA, "28", "correct"), (AREA, "28 square cm", "correct"),
    (AREA, "28cm²", "correct"),
    # c09: gpt-oss called the wrong derivative 3x - 6 correct
    (DERIV, "3x - 6", "wrong"), (DERIV, "3x^2 - 6x", "wrong"), (DERIV, "3x^2 - 6", "correct"),
    (DERIV, "f'(x) = 3x^2 - 6", "correct"),
    # c11: GLM didn't recognise 32 after the reveal
    (SUM, "32", "correct"), (SUM, "30", "wrong"), (SUM, "16/(1-1/2)", "step_forward"),
    (SUM, "just tell me", None),
    (SIMP, "8a + 2b", "correct"), (SIMP, "8a", "wrong"), (SIMP, "3a + 2b + 5a", None),
    (SIMP, "because 3a and 5a are like terms so I add them", None),
])
def test_code_judges_the_bench_attempts(problem, reply, verdict):
    assert (answer_check.check(problem, reply) or {}).get("verdict") == verdict


def test_equations_still_work():
    assert answer_check.check(LOG, "x = 10")["verdict"] == "wrong"
    assert answer_check.check(LOG, "x = 32")["verdict"] == "correct"
    assert answer_check.check("How do I solve 3x + 4 = 19?", "3x = 15")["verdict"] == "step_forward"


@pytest.mark.parametrize("problem", ["What is a function?", "What is 7?", "Explain place value"])
def test_nothing_to_check(problem):
    assert answer_check.solve_problem(problem) is None


def test_learner_text_still_never_reaches_the_parser_unsafely():
    for reply in ["__import__('os').system('ls')", "exec(1)", "9" * 300]:
        assert answer_check.check(INT, reply) is None
        assert answer_check.check(DERIV, reply) is None


# ── Leak guard ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reply,leaks", [
    ("Start at -8, then move 3 steps right. You should land at -5.", True),   # GPT-5.4 mini, c04
    ("So from -8, moving 3 steps right takes us to −5. Notice it stays negative.", True),  # Haiku
    ("-8 → -7 → -6 → -5", True),
    ("The distance from −8 to 0 is 8. How far is +3 from 0?", False),
    ("Where do you land after 3 steps right? 🙂", False),
    ("We get -5.5 here", False),
])
def test_gives_away_the_integer_answer(reply, leaks):
    assert answer_check.gives_away(reply, answer_check.answer_forms(INT)) is leaks


def test_leak_forms_skip_answers_printed_in_the_problem():
    assert answer_check.answer_forms("Is 5 + 0 = 5?") == []
    assert answer_check.answer_forms(DERIV) == []          # expressions aren't guarded
    assert "x=32" in answer_check.answer_forms(LOG)
    assert answer_check.gives_away("So x = 32 🎉", answer_check.answer_forms(LOG))
    assert not answer_check.gives_away("Can you work out 2⁵?", answer_check.answer_forms(LOG))


def test_mask_hides_the_answer_only():
    forms = answer_check.answer_forms(INT)
    out = answer_check.mask("So we land at −5. Start at -8, then -7, -6, -5.", forms)
    assert "-5" not in out and "−5" not in out and "-8" in out and "-6" in out


# ── Mid-chat greetings ───────────────────────────────────────────────────────

@pytest.mark.parametrize("reply,expected", [
    ("Hey Bench! 👋 I need a little context first. What was the question?",
     "I need a little context first. What was the question?"),
    ("Hey, good try! 😊 Remember the rule for signs?", "Good try! 😊 Remember the rule for signs?"),
    ("Hi! 😊", "Hi! 😊"),                                    # nothing else to keep
    ("Ja, -5 is right. Can you say why?", "Ja, -5 is right. Can you say why?"),
])
def test_strip_greeting(reply, expected):
    assert strip_greeting(reply) == expected


# ── Topic hints (mastery evidence lands on the right topic) ──────────────────

G8 = ["Algebraic Equations", "Algebraic Expressions", "Area and Perimeter", "Common Fractions",
      "Exponents", "Integers", "Whole numbers"]
G12 = ["Differential calculus", "Exponential and logarithmic functions",
       "Patterns, sequences and series", "Trigonometry - compound angles", "Functions and inverse functions"]


@pytest.mark.parametrize("question,topics,expected", [
    (INT, G8, "Integers"), (FRAC, G8, "Common Fractions"), (SQ, G8, "Exponents"),
    (SIMP, G8, "Algebraic Expressions"), (AREA, G8, "Area and Perimeter"),
    ("How do I solve 3x + 4 = 19?", G8, "Algebraic Equations"),
    (DERIV, G12, "Differential calculus"), (LOG, G12, "Exponential and logarithmic functions"),
    (SUM, G12, "Patterns, sequences and series"),
    ("What is a catalogue?", G8, None),   # "log" inside a word is no hint
])
def test_topic_hint(question, topics, expected):
    assert topic_hint(question, topics) == expected
