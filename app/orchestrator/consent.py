"""Guardian consent: the notices Katlego shows and the evidence it keeps.

POPIA s11(2)(a) puts the burden of proving a competent person's consent on
the responsible party, and names no method. So every consent event is one
consent_records row: which wording was shown (consent_notices, keyed by a
hash of the text sent), the WhatsApp ids of that notice and of the reply,
the reply itself, the account it came from, when, and how strong the check
was (`level`). Consent is per learner: ADD LEARNER asks again.

Research, the open legal questions and the build record:
docs/guardian-consent-findings.md.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.db import get_pool
from app.orchestrator import session
from app.queue import get_redis
from app.tutor.papers import new_code

# The wording a guardian agrees to. Any edit changes the stored version hash,
# so old records keep pointing at the text that was actually shown. Wording
# changes need sign-off (findings note, section 8).
DATA_STATEMENT = (
    "📋 *Please show this to your parent/guardian:*\n"
    "_Katlego stores this phone number, a nickname and grade, plus study "
    "progress, to personalise tutoring. It also keeps a record of this "
    "agreement, including the parent or guardian's name. No data is sold or "
    "shared. Send WITHDRAW or DELETE any time to erase a learner; erasing the "
    "last learner removes the whole household record._"
)

EXAMPLE = "_AGREE Nomsa Dlamini, mother_"
SCHOOL_CODE_LINE = "Got a Katlego code from your school? Send it instead, like _SCH-K7M2QX_."
HOW_TO_AGREE = (
    "*Parent or guardian, to agree:*\n"
    "• From your own WhatsApp (best): the learner sends *LINK* here and I "
    "give them a code for you.\n"
    "• On this phone: reply *AGREE* with your full name and how you are "
    f"related to the learner, like {EXAMPLE}.\n\n{SCHOOL_CODE_LINE}"
)

# School sign-up codes (seed/load_enrolment_codes.py). The SCH prefix keeps an
# ordinary word from being mistaken for a code.
_SCHOOL_CODE = re.compile(r"SCH[- ]?([A-Z0-9]{6})")
BAD_SCHOOL_CODE = (
    "That school code isn't one I know, or it has already been used. 🙏 "
    "Check it against the slip from your school, or ask your teacher for help."
)

NAME_NEEDED = (
    "Thank you. To keep a proper record I need the parent or guardian's name "
    "too. 🙏 Please reply *AGREE* with your full name and how you are related "
    f"to the learner, like {EXAMPLE}."
)
CONFIRMED = (
    "Thank you, that's confirmed. ✅ Send *WITHDRAW* any time to stop Katlego "
    "and erase the learner's data."
)
NOTHING_TO_CONFIRM = "Thanks! Nothing needs confirming right now. 🙂"

SAST = timezone(timedelta(hours=2))  # South Africa has no daylight saving


def notice(reason: str = "new_household") -> str:
    """The consent notice for a first sign-up, or for a sibling being added."""
    if reason == "add_learner":
        return (
            "Adding another learner needs permission from a parent or guardian "
            "for that learner too (POPIA).\n\n"
            f"{DATA_STATEMENT}\n\n{HOW_TO_AGREE}\n\nSend *CANCEL* to go back."
        )
    return (
        "Hi! I'm *Katlego* 🎓 — your CAPS study buddy on WhatsApp.\n\n"
        "Before we start, South African law (POPIA) requires permission from your "
        "parent or guardian, because I keep track of your progress to tutor you "
        "better.\n\n"
        f"{DATA_STATEMENT}\n\n{HOW_TO_AGREE}"
    )


def reprompt(reason: str = "new_household", link: str | None = None) -> str:
    text = (
        "I can only start tutoring once a parent or guardian agrees — that's "
        "the law for learners' data (POPIA). 🙏\n\n"
        "Show them the message above. They reply *AGREE* with their full name, "
        f"like {EXAMPLE}."
    )
    if link:
        text += (f"\n\nOr, from their own WhatsApp, they send Katlego *CONSENT {link}*. "
                 "I'll carry on here as soon as they agree.")
    if reason == "add_learner":
        text += "\n\nSend *CANCEL* to go back without adding a learner."
    return text


_AGREE = re.compile(r"(?:I\s+)?AGREE\b[\s,.:;!\-]*(.*)", re.I)


def agreement(text: str) -> str | None:
    """None when the message is not an agreement. Otherwise the guardian's
    name and relationship as typed, or "" when they left it out. A bare YES
    or ACCEPT never counts: too easy to send without reading the notice."""
    m = _AGREE.fullmatch(" ".join(text.split()))
    if not m:
        return None
    name = m.group(1).strip(" .,!")[:120]
    return name if sum(ch.isalpha() for ch in name) >= 3 else ""


def school_code(text: str) -> str | None:
    """The code in its stored form if the message is shaped like one."""
    m = _SCHOOL_CODE.fullmatch(text.strip().upper())
    return f"SCH-{m.group(1)}" if m else None


async def redeem_school_code(code: str) -> dict | None:
    """Spend a school code. Returns its row, or None if it is unknown or
    already used. One statement, so a code can only ever be spent once."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE enrolment_codes SET redeemed_at = now() "
            "WHERE code = $1 AND redeemed_at IS NULL "
            "RETURNING code, school, learner_ref, slip_version", code)
    return dict(row) if row else None


async def notice_sent(body: str, send_result: dict) -> dict:
    """Store the exact wording once and return what the session must remember
    about the notice on screen: its version and its WhatsApp message id."""
    version = hashlib.sha256(body.encode()).hexdigest()[:12]
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO consent_notices (version, body) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING", version, body)
    wamid = ((send_result or {}).get("messages") or [{}])[0].get("id")
    return {"version": version, "wamid": wamid}


async def record(
    account_id: int,
    *,
    method: str,
    level: str,
    replied_from: str,
    message: dict,
    notice: dict | None,
    reply_text: str | None = None,
    guardian_name: str | None = None,
    school_code: str | None = None,
) -> int:
    """Save one consent event and return its id. `message` is the inbound
    WhatsApp message that agreed: its id and its own timestamp are the
    evidence (consent time is when the guardian sent it, not when a profile
    was created later)."""
    ts = str(message.get("timestamp") or "")
    consent_at = (datetime.fromtimestamp(int(ts), timezone.utc) if ts.isdigit()
                  else datetime.now(timezone.utc))
    notice = notice or {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        consent_id = await conn.fetchval(
            """
            INSERT INTO consent_records
                (account_id, method, level, notice_version, notice_message_id,
                 reply_message_id, reply_text, replied_from, guardian_name, consent_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
            """,
            account_id, method, level, notice.get("version"), notice.get("wamid"),
            message.get("id"), reply_text, replied_from, guardian_name, consent_at,
        )
        if school_code:
            await conn.execute(
                "UPDATE enrolment_codes SET consent_record_id = $2 WHERE code = $1",
                school_code, consent_id)
    return consent_id


async def follow_up(learner_id: int, learner: str) -> str | None:
    """A short note for the guardian, when one is due, to add to a reply.

    Only for consents that rest on what was typed or sent from the learner's
    own chat. About a week after sign-up it asks the guardian to CONFIRM;
    after that it reminds them, at a longer interval, how to withdraw. Sent
    inside a reply to the learner so it costs no extra message."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE consent_records SET last_notice_at = now()
            WHERE id = (SELECT max(id) FROM consent_records WHERE learner_id = $1)
              AND level NOT IN ('school', 'second_account')
              AND COALESCE(last_notice_at, consent_at) < now() - make_interval(
                    days => CASE WHEN last_notice_at IS NULL THEN $2::int ELSE $3::int END)
            RETURNING guardian_name, consent_at, reconfirmed_at
            """,
            learner_id, settings.consent_reconfirm_days, settings.consent_reminder_days,
        )
    if not row:
        return None
    who = row["guardian_name"] or "A parent or guardian"
    on = row["consent_at"].astimezone(SAST).strftime("%-d %B %Y")
    if row["reconfirmed_at"] is None:
        return (
            f"📋 *For {learner}'s parent or guardian:* {who} agreed on {on} that "
            f"Katlego may keep {learner}'s study progress. Please reply *CONFIRM* "
            f"if that is still okay, or *WITHDRAW* to stop Katlego and erase "
            f"{learner}'s data."
        )
    return (
        f"📋 *Reminder for {learner}'s parent or guardian:* {who} agreed to "
        f"Katlego on {on}. Send *WITHDRAW* any time to stop Katlego and erase "
        f"{learner}'s data."
    )


async def confirm(learner_id: int, message_id: str | None) -> bool:
    """Record the guardian's CONFIRM. False when there was nothing to confirm."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "UPDATE consent_records SET reconfirmed_at = now(), reconfirm_message_id = $2 "
            "WHERE id = (SELECT max(id) FROM consent_records WHERE learner_id = $1) "
            "AND reconfirmed_at IS NULL RETURNING id", learner_id, message_id))


# ── The guardian confirms from their own WhatsApp ────────────────────────────
# The learner sends LINK and gets a code. The guardian sends "CONSENT <code>"
# to Katlego from their own phone, reads the notice there and agrees there.
# Because the guardian writes first, no paid template is needed. What it
# shows: a second WhatsApp account agreed (`second_account`). It does not
# show that the account belongs to a parent.
#
# Nothing from the guardian's chat goes into conversation_log and their phone
# keeps no session afterwards: the consent record (which cascades away with
# the learner) is the only trace, so erasing the learner leaves nothing
# behind under the guardian's number.

LINK_TTL_SECONDS = 48 * 3600
_LINK = re.compile(r"CONSENT[\s:\-]*([A-Z0-9]{6})")

BAD_LINK = (
    "That code isn't valid any more. 🙏 Ask the learner to send *LINK* to "
    "Katlego on their phone for a new one."
)
SAME_PHONE = (
    "That code has to come from the parent or guardian's *own* WhatsApp, not "
    "from this phone. 🙏 On this phone, the parent or guardian can reply "
    f"*AGREE* with their full name instead, like {EXAMPLE}."
)
GUARDIAN_REPROMPT = (
    "To agree, reply *AGREE* with your full name and how you are related to "
    f"the learner, like {EXAMPLE}. If you do not agree, reply *NO*."
)
GUARDIAN_DECLINED = (
    "Okay, nothing has been recorded. The learner cannot use Katlego without "
    "a parent or guardian's agreement."
)
GUARDIAN_AGREED = (
    "Your parent or guardian has agreed from their own phone. 🎉\n\n"
    "Let's set up your profile 📝 — what should I call you? Just your first "
    "name or a nickname is perfect."
)


def link_code(text: str) -> str | None:
    m = _LINK.fullmatch(text.strip().upper())
    return m.group(1) if m else None


async def start_link(sess: session.Session, phone: str) -> str:
    """Learner side: issue a single-use code for the guardian's phone."""
    r = get_redis()
    await drop_link(sess)
    while True:  # never hand out a code that is waiting on another learner
        code = new_code()
        if await r.set(f"consent_link:{code}", phone, ex=LINK_TTL_SECONDS, nx=True):
            break
    sess.data["link_code"] = code
    await session.save(sess)
    number = settings.whatsapp_public_number
    how = (f"They can tap this link on their phone:\nhttps://wa.me/{number}?text=CONSENT%20{code}"
           if number else "They send it to this same Katlego number.")
    return (
        "Ask your parent or guardian to send this message to Katlego from "
        f"*their own WhatsApp*:\n\n*CONSENT {code}*\n\n{how}\n\n"
        "The code works for 48 hours, and I'll carry on here as soon as they "
        "agree. If they have no WhatsApp of their own, they can reply *AGREE* "
        "with their full name on this phone instead."
    )


async def drop_link(sess: session.Session) -> None:
    code = sess.data.pop("link_code", None)
    if code:
        await get_redis().delete(f"consent_link:{code}")


def guardian_notice(learner_phone: str) -> str:
    return (
        "Hello 👋 I'm *Katlego*, a CAPS maths tutor on WhatsApp from TutoBuddy. "
        f"A learner using the number ending *{learner_phone[-4:]}* has asked to "
        "study with me and gave you this code as their parent or guardian. "
        "South African law (POPIA) requires your permission first.\n\n"
        "_Katlego stores the learner's phone number, a nickname and grade, plus "
        "study progress, to personalise tutoring. It also keeps a record of "
        "this agreement, including your name and this WhatsApp number. No data "
        "is sold or shared. Send WITHDRAW here any time to stop Katlego and "
        "erase the learner's data._\n\n"
        "If you are the learner's parent or guardian and you agree, reply "
        f"*AGREE* with your full name and how you are related to them, like "
        f"{EXAMPLE}. If you do not agree, reply *NO*."
    )


async def confirmed_by(phone: str) -> list[dict]:
    """Consents this WhatsApp account gave from its own phone for learners on
    other phones. A guardian's WITHDRAW is scoped to exactly these."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT r.id, r.account_id, r.learner_id, l.nickname, c.phone "
            "FROM consent_records r JOIN account_channels c ON c.account_id = r.account_id "
            "LEFT JOIN learners l ON l.id = r.learner_id "
            "WHERE r.replied_from = $1 AND r.level = 'second_account' ORDER BY r.id", phone)
    return [dict(r) for r in rows]


async def _put(sess: session.Session) -> None:
    """Keep the guardian's phone free of a session unless it has its own."""
    if sess.state or sess.data.get("guardian_for"):
        await session.save(sess)
    else:
        await session.reset(sess.phone)


async def guardian_turn(wa, sess: session.Session, phone: str, text: str, message: dict) -> bool:
    """Handle a message that belongs to the guardian's side of consent.
    True when it was answered here; False to let normal handling carry on."""
    code = link_code(text)
    if code:
        learner_phone = await get_redis().get(f"consent_link:{code}")
        if not learner_phone:
            await wa.send_text(phone, BAD_LINK)
        elif learner_phone == phone:
            await wa.send_text(phone, SAME_PHONE)  # not a second account
        else:
            body = guardian_notice(learner_phone)
            sent = await wa.send_text(phone, body)
            sess.data["guardian_for"] = {"code": code, "notice": await notice_sent(body, sent)}
            await session.save(sess)
        return True

    pending = sess.data.get("guardian_for")
    if pending:
        name = agreement(text)
        if name:
            sess.data.pop("guardian_for")
            await _put(sess)
            await _guardian_agrees(wa, phone, text, message, pending, name)
        elif name == "":
            await wa.send_text(phone, NAME_NEEDED)
        elif text.strip().upper() in {"NO", "CANCEL", "STOP"}:
            sess.data.pop("guardian_for")
            await _put(sess)
            await wa.send_text(phone, GUARDIAN_DECLINED)
        elif sess.state == "":
            await wa.send_text(phone, GUARDIAN_REPROMPT)
        else:
            return False  # this phone also has its own learner mid-chat
        return True

    if sess.state == "":
        mine = await confirmed_by(phone)
        command = text.strip().upper()
        if mine and command != "START":  # START: set up a learner on this phone too
            if command == "WITHDRAW":
                await _guardian_withdraws(wa, phone, mine)
            else:
                names = _names(mine)
                await wa.send_text(
                    phone,
                    "This number is on record as the parent or guardian who agreed "
                    f"to Katlego for {names}. Send *WITHDRAW* to stop Katlego and "
                    f"erase {names}'s data. To study with Katlego on this phone "
                    "too, send *START*.")
            return True
    # ponytail: a guardian whose own phone also has an active learner cannot
    # WITHDRAW here for a child on another phone (WITHDRAW erases the learner
    # studying on this phone). They can send WITHDRAW or DELETE on the child's
    # phone. Add a "which learner?" step if this turns out to matter.
    return False


def _names(records: list[dict]) -> str:
    return " and ".join(r["nickname"] or "a learner still signing up" for r in records)


async def _guardian_agrees(wa, phone, text, message, pending, name) -> None:
    learner_phone = await get_redis().getdel(f"consent_link:{pending['code']}")  # single use
    learner = await session.load(learner_phone) if learner_phone else None
    if (not learner or learner.state != "awaiting_consent"
            or learner.data.get("link_code") != pending["code"]):
        await wa.send_text(phone, BAD_LINK)
        return
    account_id, guardian_id = await session.create_household(learner_phone)
    consent_id = await record(
        account_id, method="guardian_whatsapp", level="second_account", replied_from=phone,
        message=message, notice=pending.get("notice"), reply_text=text, guardian_name=name,
    )
    learner.data.pop("link_code", None)
    learner.data.update(
        state="awaiting_name", account_id=account_id, guardian_id=guardian_id,
        onboarding_reason=learner.data.get("onboarding_reason", "new_household"),
        consent_id=consent_id,
    )
    try:
        await wa.send_text(learner_phone, GUARDIAN_AGREED)
    except httpx.HTTPError:
        # WhatsApp only lets Katlego write within 24 hours of the learner's
        # last message. Tell them when they next write instead.
        learner.data["consent_announce"] = True
    await session.save(learner)
    await wa.send_text(
        phone,
        f"Thank you, {name}. Your agreement is recorded. ✅ The learner can now "
        "set up their profile. Send *WITHDRAW* here any time to stop Katlego "
        "and erase their data.")


async def _guardian_withdraws(wa, phone: str, records: list[dict]) -> None:
    pool = await get_pool()
    for rec in records:
        learner = await session.load(rec["phone"])
        if rec["learner_id"] is None:
            # Agreed, but the learner has not set up a profile yet.
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM consent_records WHERE id = $1", rec["id"])
            if not await session.list_learners(rec["account_id"]):
                await session.delete_household(rec["account_id"], rec["phone"])
            elif learner.data.get("consent_id") == rec["id"]:  # a sibling being added
                learner.data.pop("consent_id")
                learner.data["state"] = "awaiting_consent"
                await session.save(learner)
            continue
        told = await session.erase_learner(
            learner, rec["phone"], rec["account_id"], rec["learner_id"], rec["nickname"])
        try:
            await wa.send_text(
                rec["phone"],
                f"A parent or guardian has withdrawn their consent from their own phone.\n\n{told}")
        except httpx.HTTPError:
            pass  # outside WhatsApp's 24-hour window; the data is erased either way
    names = _names(records)
    await wa.send_text(
        phone,
        f"Done. Katlego has stopped for {names}, and {names}'s data and your "
        "agreement record have been erased. ✅")
