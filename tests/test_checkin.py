"""Sign-up check-in over WhatsApp: starts after the grade, pauses for a real
question, resumes, finishes with a report, and seeds topic mastery."""

import json
from pathlib import Path

from tests.conftest import AGREE

BANK = Path(__file__).resolve().parent.parent / "seed" / "diagnostic"


def _onboard(chat, grade: str) -> str:
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text(AGREE)
    chat.wait_for_reply()
    chat.send_text("Lerato")
    chat.wait_for_reply()
    chat.send_text(grade)
    return chat.wait_for_reply()


def _answers(grade: int) -> dict:
    items = json.loads((BANK / f"grade_{grade:02d}.json").read_text())["items"]
    return {(i["topic"], i["kind"]): i for i in items}


def test_checkin_runs_from_sign_up_to_report(chat):
    welcome = _onboard(chat, "12")
    assert "Grade 12" in welcome and "Check-in 1/12" in welcome
    bank = _answers(12)
    reply = welcome
    for _ in range(40):
        if "Check-in done" in reply:
            break
        head = next(l for l in reply.splitlines() if l.startswith("*Check-in"))
        topic = head.split("·", 1)[1].strip(" *").replace(" (one more on this)", "")
        kind = "easier" if "one more on this" in head else "core"
        item = bank[(topic, kind)]
        # wrong on Euclidean Geometry, right everywhere else
        letter = "?" if topic == "Euclidean Geometry" else item["answer"]
        chat.send_text(letter)
        reply = chat.wait_for_reply()
    assert "Check-in done, Lerato" in reply
    assert "Euclidean Geometry" in reply.split("Needs work", 1)[1]
    assert "we start with Euclidean Geometry" in reply
    chat.send_text("REPORT")
    assert "Check-in done" in chat.wait_for_reply()


def test_a_question_pauses_the_checkin_and_checkin_resumes(chat):
    welcome = _onboard(chat, "8")
    assert "Check-in 1/22" in welcome
    chat.send_text("B")                           # HCF of 24 and 36 is 12
    assert "Check-in 2/22" in chat.wait_for_reply()
    chat.send_text("How do I solve 3x + 4 = 19?")
    reply = chat.wait_for_reply()
    assert "Check-in paused at 1/22" in reply
    chat.send_text("CHECK-IN")
    assert "Check-in 2/22" in chat.wait_for_reply()
    chat.send_text("PAUSE")
    assert "paused" in chat.wait_for_reply().lower()
