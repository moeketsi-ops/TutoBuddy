"""Guardian consent evidence (app/orchestrator/consent.py,
docs/guardian-consent-findings.md): what is stored when a guardian agrees,
and who is allowed through the gate."""

import time
import uuid

from tests.conftest import AGREE, db


def _records(phone: str) -> list[dict]:
    return db(
        "SELECT r.*, n.body AS notice_body, l.nickname FROM consent_records r "
        "JOIN account_channels c ON c.account_id = r.account_id "
        "LEFT JOIN consent_notices n ON n.version = r.notice_version "
        "LEFT JOIN learners l ON l.id = r.learner_id "
        "WHERE c.phone = $1 ORDER BY r.id", phone)


def test_agreeing_stores_what_was_shown_and_which_message_agreed(chat):
    chat.send_text("hi")
    chat.wait_for_reply()
    sent_at = int(time.time())
    agree_id = f"wamid.test.agree.{uuid.uuid4().hex}"   # unique: the gateway dedupes on it
    chat.send_text(AGREE, msg_id=agree_id)
    chat.wait_for_reply()
    chat.send_text("Thabo")
    chat.wait_for_reply()

    (rec,) = _records(chat.phone)
    assert (rec["method"], rec["level"]) == ("typed_agree", "declared")
    assert rec["reply_message_id"] == agree_id
    assert rec["reply_text"] == AGREE
    assert rec["guardian_name"] == "Nomsa Dlamini, mother"   # who said they agreed
    assert rec["replied_from"] == chat.phone
    assert rec["notice_message_id"].startswith("wamid.")   # the notice Katlego sent
    assert "POPIA" in rec["notice_body"]                    # the exact wording shown
    assert rec["nickname"] == "Thabo"                       # tied to the learner it covers
    # Consent time is the guardian's message, not the later profile creation.
    assert abs(rec["consent_at"].timestamp() - sent_at) <= 2
    link = db("SELECT consent_given_at FROM guardian_learner WHERE learner_id = $1",
              rec["learner_id"])
    assert link[0]["consent_given_at"] == rec["consent_at"]


def test_a_bare_yes_is_not_consent(chat):
    chat.send_text("hi")
    chat.wait_for_reply()
    for word in ("YES", "ACCEPT", "ok"):
        chat.send_text(word)
        assert "AGREE" in chat.wait_for_reply()   # re-prompt, still at the gate
    chat.send_text("AGREE")                       # agreement without a name
    assert "full name" in chat.wait_for_reply()
    assert _records(chat.phone) == []


def test_agreement_parsing():
    from app.orchestrator.consent import agreement

    assert agreement("AGREE Nomsa Dlamini, mother") == "Nomsa Dlamini, mother"
    assert agreement("i agree - Sipho Nkosi (father)") == "Sipho Nkosi (father)"
    assert agreement("AGREE") == "" and agreement("I agree.") == ""   # name missing
    for not_consent in ("YES", "ACCEPT", "AGREED", "I do not agree", "Nomsa AGREE", "hi"):
        assert agreement(not_consent) is None, not_consent


def test_each_sibling_gets_their_own_consent_record(onboarded_chat):
    onboarded_chat.send_text("ADD LEARNER")
    notice = onboarded_chat.wait_for_reply()
    assert "AGREE" in notice and "CANCEL" in notice
    onboarded_chat.send_text("Naledi")              # a name is not consent
    assert "AGREE" in onboarded_chat.wait_for_reply()
    onboarded_chat.send_text(AGREE)
    assert "call you" in onboarded_chat.wait_for_reply().lower()
    onboarded_chat.send_text("Naledi")
    onboarded_chat.wait_for_reply()

    first, second = _records(onboarded_chat.phone)
    assert (first["nickname"], second["nickname"]) == ("Thabo", "Naledi")
    assert first["notice_version"] != second["notice_version"]   # different wording shown


def test_cancel_leaves_the_sibling_step_without_adding_anyone(onboarded_chat):
    onboarded_chat.send_text("ADD LEARNER")
    onboarded_chat.wait_for_reply()
    onboarded_chat.send_text("CANCEL")
    assert "Thabo" in onboarded_chat.wait_for_reply()
    onboarded_chat.send_text("SWITCH")               # still just Thabo, and active
    assert "ADD LEARNER" in onboarded_chat.wait_for_reply()
    assert len(_records(onboarded_chat.phone)) == 1


def _backdate(phone: str, column: str, days: int) -> None:
    db(f"UPDATE consent_records SET {column} = now() - make_interval(days => $2) "
       "WHERE replied_from = $1", phone, days)


def test_guardian_is_asked_to_confirm_after_a_week_then_reminded(onboarded_chat):
    c = onboarded_chat
    c.send_text("HELP")
    assert "CONFIRM" not in c.wait_for_reply()        # nothing due on day one

    _backdate(c.phone, "consent_at", 8)
    c.send_text("HELP")
    note = c.wait_for_reply()
    assert "Nomsa Dlamini" in note and "CONFIRM" in note and "WITHDRAW" in note
    c.send_text("HELP")
    assert "CONFIRM" not in c.wait_for_reply()        # asked once, not on every message

    confirm_id = f"wamid.test.confirm.{uuid.uuid4().hex}"
    c.send_text("confirm", msg_id=confirm_id)
    assert "confirmed" in c.wait_for_reply().lower()
    (rec,) = _records(c.phone)
    assert rec["reconfirmed_at"] is not None and rec["reconfirm_message_id"] == confirm_id

    _backdate(c.phone, "last_notice_at", 31)
    c.send_text("HELP")
    reminder = c.wait_for_reply()
    assert "Reminder" in reminder and "WITHDRAW" in reminder and "CONFIRM" not in reminder


def test_withdraw_erases_the_learner_and_the_consent_record(onboarded_chat):
    onboarded_chat.send_text("WITHDRAW")
    assert "erased" in onboarded_chat.wait_for_reply().lower()
    assert db("SELECT 1 FROM consent_records WHERE replied_from = $1", onboarded_chat.phone) == []
    onboarded_chat.send_text("hi")
    assert "POPIA" in onboarded_chat.wait_for_reply()
