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
from datetime import datetime, timezone

from app.db import get_pool

# The wording a guardian agrees to. Any edit changes the stored version hash,
# so old records keep pointing at the text that was actually shown. Wording
# changes need sign-off (findings note, question 8).
DATA_STATEMENT = (
    "📋 *Please show this to your parent/guardian:*\n"
    "_Katlego stores this phone number, a nickname and grade, plus study "
    "progress, to personalise tutoring. No data is sold or shared. Send "
    "DELETE any time to erase a learner; erasing the last learner removes "
    "the whole household record._"
)


def notice(reason: str = "new_household") -> str:
    """The consent notice for a first sign-up, or for a sibling being added."""
    if reason == "add_learner":
        return (
            "Adding another learner needs permission from a parent or guardian "
            "for that learner too (POPIA).\n\n"
            f"{DATA_STATEMENT}\n\n"
            "If your parent or guardian agrees, ask them to reply *AGREE* to "
            "continue. Send *CANCEL* to go back."
        )
    return (
        "Hi! I'm *Katlego* 🎓 — your CAPS study buddy on WhatsApp.\n\n"
        "Before we start, South African law (POPIA) requires permission from your "
        "parent or guardian, because I keep track of your progress to tutor you "
        "better.\n\n"
        f"{DATA_STATEMENT}\n\n"
        "If your parent or guardian agrees, ask them to reply *AGREE* to continue."
    )


def reprompt(reason: str = "new_household") -> str:
    text = (
        "I can only start tutoring once a parent or guardian replies *AGREE* — "
        "that's the law for learners' data (POPIA). 🙏\n\n"
        "Show them the message above, and reply *AGREE* when they say it's okay."
    )
    if reason == "add_learner":
        text += "\n\nSend *CANCEL* to go back without adding a learner."
    return text


def agreed(text: str) -> bool:
    """A bare YES or ACCEPT no longer counts: it is too easy to send without
    reading the notice."""
    return text.strip().strip(".!").upper() in {"AGREE", "I AGREE"}


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
        return await conn.fetchval(
            """
            INSERT INTO consent_records
                (account_id, method, level, notice_version, notice_message_id,
                 reply_message_id, reply_text, replied_from, guardian_name, consent_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
            """,
            account_id, method, level, notice.get("version"), notice.get("wamid"),
            message.get("id"), reply_text, replied_from, guardian_name, consent_at,
        )
