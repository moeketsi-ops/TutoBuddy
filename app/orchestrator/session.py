"""Session + POPIA consent state machine (Redis-backed).

States: awaiting_consent → awaiting_grade → active.
POPIA §34–35: a "competent person" (parent/guardian) must consent before we
process a child's personal information — so the consent gate runs before any
profiling or tutoring, and we minimise data (nickname + grade only).
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

GRADE_PROMPT = (
    "Thank you! Consent noted. ✅\n\n"
    "One last thing — *what grade are you in?* Reply with a number from 8 to 12."
)

GRADE_REPROMPT = "Please reply with just your grade number, from *8* to *12*. 😊"


def welcome_message(grade: int) -> str:
    return (
        f"Awesome — Grade {grade} it is! 🎉 You're all set.\n\n"
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


async def record_grade(phone: str, grade: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE learners SET grade = $2 WHERE phone = $1", phone, grade
        )


async def delete_learner(phone: str) -> None:
    """POPIA right to deletion — wipes profile, history and session."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM learners WHERE phone = $1", phone)
        await conn.execute("DELETE FROM conversation_log WHERE phone = $1", phone)
    await reset(phone)
