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
    assert _records(chat.phone) == []


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
