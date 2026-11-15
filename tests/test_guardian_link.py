"""The guardian confirms from their own WhatsApp with a code
(app/orchestrator/consent.py, "The guardian confirms from their own
WhatsApp"). Two simulated phones: the learner's and the guardian's."""

import asyncio
import os
import re

import httpx
import redis.asyncio as aioredis

from tests.conftest import AGREE, MOCKWA, Chat, db


def _session_exists(phone: str) -> bool:
    async def q():
        r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        try:
            return bool(await r.exists(f"sess:{phone}"))
        finally:
            await r.aclose()
    return asyncio.run(q())


def _link(learner: Chat) -> str:
    """The learner asks for a code; returns it."""
    learner.send_text("hi")
    assert "LINK" in learner.wait_for_reply()        # the notice offers this route
    learner.send_text("link")
    reply = learner.wait_for_reply()
    return re.search(r"CONSENT ([A-Z0-9]{6})", reply).group(1)


def _records(guardian: Chat) -> list[dict]:
    return db(
        "SELECT r.method, r.level, r.guardian_name, r.reply_text, n.body, l.nickname, c.phone "
        "FROM consent_records r JOIN account_channels c ON c.account_id = r.account_id "
        "LEFT JOIN consent_notices n ON n.version = r.notice_version "
        "LEFT JOIN learners l ON l.id = r.learner_id WHERE r.replied_from = $1", guardian.phone)


def _sign_up_with_guardian(learner: Chat, guardian: Chat) -> None:
    guardian.send_text(f"CONSENT {_link(learner)}")
    guardian.wait_for_reply()
    guardian.send_text(AGREE)
    guardian.wait_for_reply()
    learner.wait_for_reply()                          # "your guardian agreed", name prompt
    for msg in ("Thabo", "11"):
        learner.send_text(msg)
        learner.wait_for_reply()


def test_guardian_agrees_from_their_own_phone(chat):
    guardian = Chat()
    code = _link(chat)

    guardian.send_text(f"consent {code}")
    notice = guardian.wait_for_reply()
    assert chat.phone[-4:] in notice and "AGREE" in notice and "WITHDRAW" in notice
    guardian.send_text("AGREE")                       # a name is required here too
    assert "full name" in guardian.wait_for_reply()
    guardian.send_text(AGREE)
    assert "recorded" in guardian.wait_for_reply()

    assert "call you" in chat.wait_for_reply().lower()   # the learner is told and carries on
    chat.send_text("Thabo")
    assert "grade" in chat.wait_for_reply().lower()

    (rec,) = _records(guardian)
    assert (rec["method"], rec["level"]) == ("guardian_whatsapp", "second_account")
    assert rec["guardian_name"] == "Nomsa Dlamini, mother"
    assert rec["phone"] == chat.phone and rec["nickname"] == "Thabo"
    assert "this WhatsApp number" in rec["body"]         # the wording the guardian saw
    # The guardian's phone is left with no chat rows and no session.
    assert db("SELECT 1 FROM conversation_log WHERE phone = $1", guardian.phone) == []
    assert not _session_exists(guardian.phone)

    late = Chat()                                         # the code worked once
    late.send_text(f"CONSENT {code}")
    assert "isn't valid" in late.wait_for_reply()


def test_the_learners_own_phone_cannot_stand_in_for_the_guardian(chat):
    code = _link(chat)
    chat.send_text(f"CONSENT {code}")
    assert "own" in chat.wait_for_reply()
    chat.send_text("how do I factorise?")                 # still at the gate
    reply = chat.wait_for_reply()
    assert "AGREE" in reply and code in reply             # reminded of the waiting code
    assert db("SELECT 1 FROM consent_records r JOIN account_channels c "
              "ON c.account_id = r.account_id WHERE c.phone = $1", chat.phone) == []


def test_guardian_can_decline(chat):
    guardian = Chat()
    guardian.send_text(f"CONSENT {_link(chat)}")
    guardian.wait_for_reply()
    guardian.send_text("what is this?")
    assert "AGREE" in guardian.wait_for_reply()
    guardian.send_text("no")
    assert "nothing has been recorded" in guardian.wait_for_reply().lower()
    assert _records(guardian) == [] and not _session_exists(guardian.phone)
    chat.send_text("hello?")
    assert "AGREE" in chat.wait_for_reply()               # learner still at the gate


def test_learner_is_told_on_their_next_message_if_whatsapp_blocks_the_notice(chat):
    guardian = Chat()
    guardian.send_text(f"CONSENT {_link(chat)}")
    guardian.wait_for_reply()
    httpx.post(f"{MOCKWA}/block/{chat.phone}")            # outside the 24-hour window
    guardian.send_text(AGREE)
    assert "recorded" in guardian.wait_for_reply()
    chat.send_text("did she do it?")                      # must not be taken as a name
    assert "agreed" in chat.wait_for_reply()
    chat.send_text("Thabo")
    assert "Thabo" in chat.wait_for_reply() and len(_records(guardian)) == 1


def test_guardian_withdraws_from_their_own_phone(chat):
    guardian = Chat()
    _sign_up_with_guardian(chat, guardian)

    # A second account backs this consent, so no CONFIRM note in the learner's chat.
    db("UPDATE consent_records SET consent_at = now() - interval '40 days' "
       "WHERE replied_from = $1", guardian.phone)
    chat.send_text("HELP")
    assert "CONFIRM" not in chat.wait_for_reply()

    guardian.send_text("hello")
    menu = guardian.wait_for_reply()
    assert "Thabo" in menu and "WITHDRAW" in menu
    guardian.send_text("withdraw")
    assert "erased" in guardian.wait_for_reply()
    assert "withdrawn" in chat.wait_for_reply()           # the learner's chat is told

    assert _records(guardian) == []
    assert db("SELECT 1 FROM account_channels WHERE phone = $1", chat.phone) == []
    assert db("SELECT 1 FROM conversation_log WHERE phone = ANY($1::text[])",
              [chat.phone, guardian.phone]) == []
    assert not _session_exists(chat.phone) and not _session_exists(guardian.phone)
    guardian.send_text("hi")                              # an ordinary number again
    assert "POPIA" in guardian.wait_for_reply()


def test_guardian_withdraws_one_sibling_and_the_other_keeps_studying(onboarded_chat):
    guardian = Chat()
    c = onboarded_chat                                    # Thabo, agreed on this phone
    c.send_text("ADD LEARNER")
    c.wait_for_reply()
    c.send_text("LINK")
    code = re.search(r"CONSENT ([A-Z0-9]{6})", c.wait_for_reply()).group(1)
    guardian.send_text(f"CONSENT {code}")
    guardian.wait_for_reply()
    guardian.send_text(AGREE)
    guardian.wait_for_reply()
    c.wait_for_reply()
    for msg in ("Naledi", "9"):
        c.send_text(msg)
        c.wait_for_reply()

    guardian.send_text("WITHDRAW")                        # covers Naledi only
    assert "Naledi" in guardian.wait_for_reply()
    assert "Switched to Thabo" in c.wait_for_reply()
    left = db("SELECT l.nickname FROM learners l JOIN account_channels c "
              "ON c.account_id = l.account_id WHERE c.phone = $1", c.phone)
    assert [r["nickname"] for r in left] == ["Thabo"]


def test_own_wa_me_link_survives_the_output_filter(monkeypatch):
    from app.config import settings
    from app.orchestrator.safety import sanitize_output

    monkeypatch.setattr(settings, "whatsapp_public_number", "27600000000")
    keep = "https://wa.me/27600000000?text=CONSENT%20K7M2QX"
    assert keep in sanitize_output(f"Tap {keep}")
    assert "wa.me/27611111111" not in sanitize_output("Tap https://wa.me/27611111111?text=hi")
    assert "example.com" not in sanitize_output("See https://example.com/x")
