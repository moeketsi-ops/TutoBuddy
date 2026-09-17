"""Session + POPIA consent state machine (Redis-backed).

States: awaiting_consent → awaiting_name → awaiting_grade → active.
POPIA §34–35: a "competent person" (parent/guardian) must consent before we
process a child's personal information — so the consent gate runs before any
profiling or tutoring. The name step exists so "profile creation" is an
explicit, visible moment for the learner (and for anyone testing/demoing
this) rather than silently trusting whatever contact name the WhatsApp
payload happens to carry -- unreliable in the mock (always "Demo Learner")
and not guaranteed to be a name a learner wants used on the real WhatsApp
API either. We still minimise data: nickname + grade only.
"""

import json

from app.db import get_pool
from app.queue import get_redis

SESSION_TTL_SECONDS = 30 * 24 * 3600

CONSENT_MESSAGE = (
    "Hi! I'm *Katlego* 🎓 — your CAPS study buddy on WhatsApp.\n\n"
    "Before we start, South African law (POPIA) requires permission from your "
    "parent or guardian, because I keep track of your progress to tutor you "
    "better.\n\n"
    "📋 *Please show this to your parent/guardian:*\n"
    "_Katlego stores this phone number, a nickname and grade, plus study "
    "progress, to personalise tutoring. No data is sold or shared. Delete "
    "everything any time by sending DELETE._\n\n"
    "If your parent or guardian agrees, ask them to reply *AGREE* to continue."
)

CONSENT_REPROMPT = (
    "I can only start tutoring once a parent or guardian replies *AGREE* — "
    "that's the law for learners' data (POPIA). 🙏\n\n"
    "Show them the message above, and reply *AGREE* when they say it's okay."
)

NAME_PROMPT = (
    "Thank you! Consent noted. ✅\n\n"
    "Let's set up your profile 📝 — what should I call you? Just your first "
    "name or a nickname is perfect."
)

NAME_REPROMPT = (
    "I didn't quite catch a name there — just send me a word or two to call "
    "you by. 😊"
)

_RESERVED_NAMES = {"HELP", "RESET", "DELETE", "AGREE", "YES", "ACCEPT", "I AGREE"}
_NAME_MAX_LEN = 40


def clean_name(text: str) -> str | None:
    """Returns a usable nickname from free text, or None if it should be
    re-prompted (empty, or one of the command words a learner might send by
    habit/confusion at this step)."""
    cleaned = text.strip()[:_NAME_MAX_LEN]
    if not cleaned or cleaned.upper() in _RESERVED_NAMES:
        return None
    return cleaned


def grade_prompt(name: str) -> str:
    return (
        f"Nice to meet you, {name}! 🎉\n\n"
        "One last thing — *what grade are you in?* Reply with a number from 8 to 12."
    )


GRADE_REPROMPT = "Please reply with just your grade number, from *8* to *12*. 😊"


def welcome_message(name: str, grade: int) -> str:
    return (
        f"Awesome, {name} — Grade {grade} it is! 🎉 Your profile's all set.\n\n"
        "Ask me anything from your Maths syllabus, for example:\n"
        "• _How do I factorise x² + 5x + 6?_\n"
        "• 🎤 send a *voice note* with your question\n"
        "• 📸 send a *photo* of the problem\n\n"
        "I won't just give answers — I'll coach you to find them. Let's go! 💪"
    )


class Session:
    def __init__(self, phone: str, data: dict):
        self.phone = phone
        self.data = data

    @property
    def state(self) -> str:
        return self.data.get("state", "")

    @property
    def grade(self) -> int:
        return int(self.data.get("grade", 11))


async def load(phone: str) -> Session:
    r = get_redis()
    raw = await r.get(f"sess:{phone}")
    return Session(phone, json.loads(raw) if raw else {})


async def save(sess: Session) -> None:
    r = get_redis()
    await r.set(f"sess:{sess.phone}", json.dumps(sess.data), ex=SESSION_TTL_SECONDS)


async def reset(phone: str) -> None:
    await get_redis().delete(f"sess:{phone}")


async def record_consent(phone: str, name: str) -> None:
    """Creates the learner row at consent time. `name` here is only the
    WhatsApp contact name carried in the webhook payload (a best-effort
    placeholder) -- record_name() below overwrites it once the learner
    actually answers the new profile-creation name prompt."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO learners (phone, display_name, consent_given_at)
            VALUES ($1, $2, now())
            ON CONFLICT (phone)
            DO UPDATE SET consent_given_at = now(), display_name = $2
            """,
            phone,
            name,
        )


async def record_name(phone: str, name: str) -> None:
    """Overwrites the placeholder WhatsApp contact name with the nickname
    the learner actually chose during profile creation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE learners SET display_name = $2 WHERE phone = $1", phone, name
        )


async def record_grade(phone: str, grade: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE learners SET grade = $2 WHERE phone = $1", phone, grade
        )


async def delete_learner(phone: str) -> None:
    """POPIA right to deletion — wipes profile, history and session.

    Deliberately does NOT touch safeguarding_flags: a self-harm/abuse
    disclosure is a duty-of-care/legal record, not ordinary profile data,
    and is not tied to this table by a foreign key for exactly that reason
    (see the comment on safeguarding_flags in app/db.py)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM learners WHERE phone = $1", phone)
        await conn.execute("DELETE FROM conversation_log WHERE phone = $1", phone)
    await reset(phone)
