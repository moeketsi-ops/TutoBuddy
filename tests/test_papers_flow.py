"""Past papers, test prep and study squads over WhatsApp (stub model: code
marks the final answers it can check)."""

import re

from tests.conftest import Chat


def _onboard(chat, name="Ayanda", grade="12"):
    for msg in ("hi", "AGREE", name, grade):
        chat.send_text(msg)
        reply = chat.wait_for_reply()
    chat.send_text("PAUSE")                  # park the sign-up check-in
    chat.wait_for_reply()
    return reply


def test_paper_marked_against_the_memo_with_help_and_report(chat):
    _onboard(chat)
    chat.send_text("PAPER")
    menu = chat.wait_for_reply()
    assert "Grade 12 past papers" in menu and "1. Gauteng" in menu
    chat.send_text("1")
    q = chat.wait_for_reply()
    assert "Question 1.1.1" in q and "x(2x - 3) = 0" in q
    chat.send_text("x = 0 or x = 3/2")
    marked = chat.wait_for_reply()
    assert "2/2" in marked and "Question 1.1.2" in marked
    chat.send_text("HELP")
    helped = chat.wait_for_reply()
    assert "won't count" in helped and "NEXT = next question" in helped
    chat.send_text("NEXT")
    assert "Question 1.1.3" in chat.wait_for_reply()
    chat.send_text("x = 5")                  # wrong: -4/3 < x < 2 (no code check: memo shown)
    assert "Memo" in chat.wait_for_reply()
    chat.send_text("STOP")
    report = chat.wait_for_reply()
    assert "done, Ayanda" in report and "Marks: *2/5*" in report and "Worked through with me" in report


def test_learner_says_test_then_prep(chat):
    _onboard(chat, "Musa", "12")
    chat.send_text("I'm writing a test on Friday on sequences and series")
    plan = chat.wait_for_reply()
    assert "Noted: test" in plan and "Patterns, sequences and series" in plan and "PREP" in plan
    chat.send_text("PREP")
    first = chat.wait_for_reply()
    assert "Test prep: Patterns, sequences and series" in first and "Patterns, sequences and series" in first
    chat.send_text("STOP")
    assert "done, Musa" in chat.wait_for_reply()


def test_test_without_topics_asks_for_them(chat):
    _onboard(chat, "Zola", "11")
    chat.send_text("we have a maths test tomorrow")
    assert "Which topics" in chat.wait_for_reply()
    chat.send_text("number patterns")
    assert "Number patterns" in chat.wait_for_reply()


def test_study_squad():
    a, b = Chat(), Chat()
    _onboard(a, "Lwazi", "12")
    _onboard(b, "Neo", "12")
    a.send_text("SQUAD NEW")
    created = a.wait_for_reply()
    code = re.search(r"SQUAD JOIN (\w{6})", created).group(1)
    b.send_text(f"SQUAD JOIN {code}")
    assert f"squad *{code}*" in b.wait_for_reply()
    a.send_text("SQUAD PAPER")
    assert "Pick the squad's paper" in a.wait_for_reply()
    a.send_text("1")
    assert "Squad paper set" in a.wait_for_reply()
    a.send_text("SQUAD START")
    assert "Question 1.1.1" in a.wait_for_reply()
    a.send_text("x = 0 or x = 1.5")
    a.wait_for_reply()
    a.send_text("STOP")
    assert "SQUAD RESULTS" in a.wait_for_reply()
    b.send_text("SQUAD RESULTS")
    board = b.wait_for_reply()
    assert "Lwazi: 2/2" in board and "Neo: not finished yet" in board
