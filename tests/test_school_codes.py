"""School route: a code issued for a signed slip stands in for the typed
AGREE (seed/load_enrolment_codes.py, app/orchestrator/consent.py)."""

import uuid

from seed.load_enrolment_codes import load
from tests.conftest import Chat, db, run_with_app_db

SLIP = "Test slip wording: I agree to Katlego tutoring my child."


def _issue(rows: list[dict], school: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    school = school or f"Test High {uuid.uuid4().hex[:6]}"
    return school, run_with_app_db(lambda: load(rows, school, SLIP))


def test_codes_only_for_returned_slips_and_stable_on_reload():
    rows = [{"learner_ref": "8A-01", "signed_on": "2026-11-03"},
            {"learner_ref": "8A-02", "signed_on": ""}]           # slip not back
    school, issued = _issue(rows)
    assert [ref for ref, _ in issued] == ["8A-01"]
    assert issued[0][1].startswith("SCH-")
    rows[1]["signed_on"] = "2026-11-05"                           # now it is
    _, again = _issue(rows, school)
    assert again[0] == issued[0] and len(again) == 2              # first code unchanged


def test_school_code_signs_a_learner_up_without_agree(chat):
    school, ((_, code),) = _issue([{"learner_ref": "8B-07", "signed_on": "2026-11-03"}])
    chat.send_text("hi")
    assert "school" in chat.wait_for_reply().lower()             # the notice offers the code route
    chat.send_text(code.lower().replace("-", " "))                # typed loosely
    assert "call you" in chat.wait_for_reply().lower()
    chat.send_text("Zanele")
    chat.wait_for_reply()

    (rec,) = db(
        "SELECT r.method, r.level, r.reply_text, n.body, e.school, e.learner_ref, l.nickname "
        "FROM consent_records r JOIN enrolment_codes e ON e.consent_record_id = r.id "
        "JOIN consent_notices n ON n.version = r.notice_version "
        "JOIN learners l ON l.id = r.learner_id WHERE r.replied_from = $1", chat.phone)
    assert (rec["method"], rec["level"]) == ("school_code", "school")
    assert rec["body"] == SLIP                                    # the wording the parent signed
    assert (rec["school"], rec["learner_ref"], rec["nickname"]) == (school, "8B-07", "Zanele")

    other = Chat()                                                # a code works once
    other.send_text("hi")
    other.wait_for_reply()
    other.send_text(code)
    assert "already been used" in other.wait_for_reply()
    other.send_text("SCH-ZZZZZZ")                                 # and unknown codes are refused
    assert "already been used" in other.wait_for_reply()
    assert db("SELECT 1 FROM consent_records WHERE replied_from = $1", other.phone) == []


def test_erasing_the_learner_keeps_the_code_spent(chat):
    _, ((_, code),) = _issue([{"learner_ref": "9C-11", "signed_on": "2026-11-03"}])
    for msg in ("hi", code, "Sizwe", "9", "DELETE"):
        chat.send_text(msg)
        reply = chat.wait_for_reply()
    assert "erased" in reply.lower()
    (row,) = db("SELECT redeemed_at, consent_record_id FROM enrolment_codes WHERE code = $1", code)
    assert row["redeemed_at"] is not None and row["consent_record_id"] is None
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text(code)                                          # no reuse without a new slip
    assert "already been used" in chat.wait_for_reply()
