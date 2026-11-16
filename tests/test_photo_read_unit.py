"""Homework photo read into text (PHOTO_PIPELINE=read): the pure parts.
The worker path is exercised by `python -m evals.bench.media.run chats --stub`."""

from app.adapters.llm import parse_photo_read
from app.tutor import answer_check
from app.worker import photo_message


def test_working_is_judged_line_by_line():
    got, line = answer_check.check_working("Solve 2x + 3 = 11", ["2x = 11 + 3", "2x = 14", "x = 7"])
    assert (got["verdict"], line) == ("wrong", 1)
    got, line = answer_check.check_working("Solve 3(x + 4) = 21", ["3x + 12 = 21", "3x = 9", "x = 3"])
    assert (got["verdict"], line) == ("correct", None)
    got, line = answer_check.check_working("Solve x^2 - 5x + 6 = 0", ["(x - 2)(x + 3) = 0", "x = 2 or x = -3"])
    assert (got["verdict"], line) == ("wrong", 1)
    got, line = answer_check.check_working("Calculate 2/3 + 1/4", ["= 3/7"])
    assert (got["verdict"], line) == ("wrong", 1)
    # a line code can't read: the model judges, as before
    assert answer_check.check_working("Solve 2x + 3 = 11", ["take 3 from both sides", "x = 4"]) == (None, None)


def test_answer_check_reads_common_phrasings():
    # found by the media bench: each of these used to be misjudged
    assert answer_check.check("Solve for x: 3x + 4 = 19", "x = 5")["verdict"] == "correct"
    assert answer_check.check("Solve for x: 3x + 4 = 19", "x = 7")["verdict"] == "wrong"
    assert answer_check.check("Calculate: 2/3 + 1/4", "11/12")["verdict"] == "correct"
    assert answer_check.check("What is 3/4 ÷ 1/2?", "3/2")["verdict"] == "correct"
    assert answer_check.check("What is 3/4 ÷ 1/2?", "3/8")["verdict"] == "wrong"
    assert answer_check.check("What is 12 ÷ 4?", "3")["verdict"] == "correct"
    # a table of values is not an equation to solve
    assert answer_check.solve_problem("Table: x = 1, 2, 3, 4 and y = 5, 8, 11, ?. Find the rule.") is None


def test_parse_photo_read():
    raw = 'Sure:\n```json\n{"legible": true, "problem": "Solve 2x + 3 = 11", "working": ["2x = 14", " "], "values": []}\n```'
    assert parse_photo_read(raw) == {"problem": "Solve 2x + 3 = 11", "working": ["2x = 14"], "values": []}
    assert parse_photo_read('{"legible": false, "problem": "", "working": []}') is None
    assert parse_photo_read("I can't read this") is None
    assert parse_photo_read(None) is None


def test_photo_message_reads_like_a_learner():
    msg = photo_message({"problem": "Solve 2x + 3 = 11", "working": ["2x = 14", "x = 7"]}, "Where did I go wrong?")
    assert msg == "Solve 2x + 3 = 11\nMy working:\n1) 2x = 14\n2) x = 7\nWhere did I go wrong?"


def test_control_characters_never_reach_the_learner_or_the_log():
    from app.orchestrator.safety import sanitize_output
    assert sanitize_output("Now combine \x00-8 + 3\x00 first.\nWhat do you get?") == \
        "Now combine -8 + 3 first.\nWhat do you get?"
    assert sanitize_output("So \x1b[0m-8 + 3 is \x1b[?25l\x1b[?25h11/12") == "So -8 + 3 is 11/12"
