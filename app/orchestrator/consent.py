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

from app.config import settings
from app.db import get_pool

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
    "*Parent or guardian:* to agree, reply *AGREE* with your full name and how "
    f"you are related to the learner, like {EXAMPLE}.\n\n{SCHOOL_CODE_LINE}"
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


def reprompt(reason: str = "new_household") -> str:
    text = (
        "I can only start tutoring once a parent or guardian agrees — that's "
        "the law for learners' data (POPIA). 🙏\n\n"
        "Show them the message above. They reply *AGREE* with their full name, "
        f"like {EXAMPLE}."
    )
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
