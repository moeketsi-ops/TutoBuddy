"""Spoken maths -> symbols (app.tutor.spoken), on transcripts Whisper really
produced in the media bench, and on ordinary sentences that must not change."""

import pytest

from app.tutor import answer_check
from app.tutor.spoken import echo, to_symbols


@pytest.mark.parametrize("heard, want", [
    ("How do I solve 3x plus 4 equals 19?", "How do I solve 3x + 4 = 19?"),
    ("x equals negative 5.", "x = -5."),
    ("X equals seven.", "X = 7."),
    ("Negative 5", "-5"),
    ("minus 11.", "-11."),
    ("five", "5"),
    ("11 over 12.", "11/12."),
    ("x equals 2 or x equals 3.", "x = 2 or x = 3."),
    ("3x squared minus 6", "3x^2 - 6"),
    ("How do I add two thirds and one quarter?", "How do I add 2/3 and 1/4?"),
    ("What is 3 over 4 divided by 1 half?", "What is 3/4 ÷ 1/2?"),
    ("What is three squared plus four squared?", "What is 3^2 + 4^2?"),
    ("What is 2 to the power of negative 3?", "What is 2^-3?"),
    ("How do I simplify x to the power of 5 times x to the power of 3?", "How do I simplify x^5 × x^3?"),
    ("Calculate minus 6 times minus 7.", "Calculate -6 × -7."),
    ("What is 5 minus negative 2?", "What is 5 - -2?"),
    ("Solve 2 bracket x minus 1 bracket equals 10.", "Solve 2(x - 1) = 10."),
    ("expand 3, open bracket, x plus 4, close bracket.", "expand 3(x + 4)."),
    ("simplify 3 a plus 2 b plus 5 a", "simplify 3a + 2b + 5a"),
    ("Solve x over 3 plus 2 equals 5.", "Solve x/3 + 2 = 5."),
    ("Find the derivative of f of x equals x cubed minus 6x.", "Find the derivative of f(x) = x^3 - 6x."),
    ("How do I factorise x squared plus five x plus six?", "How do I factorise x^2 + 5x + 6?"),
    ("A taxi travels 120 kilometers in one and a half hours.", "A taxi travels 120 kilometers in 1.5 hours."),
    ("What is fifteen percent of two hundred and forty rand?", "What is 15% of 240 rand?"),
    ("Ndkabanga yukafi x equals 5.", "Ndkabanga yukafi x = 5."),
])
def test_maths_phrases_become_symbols(heard, want):
    assert to_symbols(heard) == want


@pytest.mark.parametrize("sentence", [
    "Can you go over this one more time?",
    "I tried it and got it wrong, plus I don't get the last step.",
    "Is the answer negative?",
    "This one is hard, can you give me another one",
    "What are brackets for?",
    "Thanks Katlego, that helps a lot.",
    "How do I solve 3x + 4 = 19?",       # already symbols: untouched
    "x = -5",
])
def test_ordinary_sentences_are_left_alone(sentence):
    assert to_symbols(sentence) == sentence


def test_a_misheard_note_is_not_made_worse():
    # real recording, 15 Nov: "two bracket x minus one bracket" was heard as below
    out = to_symbols("Solve two brackets times minus one bracket equals ten.")
    assert "(" not in out and ")" not in out


def test_spoken_answers_reach_the_code_check():
    check = answer_check.check
    assert check("How do I solve 3x + 4 = 19?", to_symbols("x equals 5."))["verdict"] == "correct"
    assert check("Solve 2x + 16 = 6", to_symbols("x equals negative 5."))["verdict"] == "correct"
    assert check("How do I solve 3x + 4 = 19?", to_symbols("3x equals 15"))["verdict"] == "step_forward"
    assert check("What is -8 + 3?", to_symbols("Minus 11."))["verdict"] == "wrong"
    assert check("How do I add 2/3 and 1/4?", to_symbols("11 over 12."))["verdict"] == "correct"
    # a spoken question is now a problem code can solve
    assert answer_check.solve_problem(to_symbols("What is three squared plus four squared?"))["answer"] == "25"
    assert answer_check.solve_problem(to_symbols("Solve 2 bracket x minus 1 bracket equals 10."))["solutions"] == ["6"]


def test_echo_drops_what_whisper_could_not_make_sense_of():
    heard = to_symbols("Sarubornaka Flethor, Angisala Angisais, how do I solve 3x plus 4 equals 19?")
    assert echo(heard) == "How do I solve 3x + 4 = 19?"
    assert echo("Hello Kahlilho, Ek-Würsten-Ni-Hirdy-Som-Ni. Solve 2(x - 1) = 10.") == "Solve 2(x - 1) = 10."
    assert echo("x = 5.") == "x = 5."
    assert echo("Thanks Katlego, that helps.") == "Thanks Katlego, that helps."   # nothing to trim to


def test_misheard_maths_is_flagged_and_clear_maths_is_not():
    from app.tutor.spoken import unclear
    # the real misheard note
    assert unclear(to_symbols("I'm going to solve two brackets times minus one bracket equals 10."))
    assert unclear("Solve 2 times -1 = 10")
    for heard in ("How do I solve 3x plus 4 equals 19?", "x equals negative 5.", "Solve 2 bracket x minus 1 bracket equals 10.",
                  "What is 3 over 4 divided by 1 half?", "I tried it 3 times and got it wrong", "Can you go over this one more time?",
                  "What is 15% of 240 rand?", "minus 11."):
        assert not unclear(to_symbols(heard)), heard
