"""Session + household account model (Redis-backed session, Postgres for
accounts/guardians/learners -- see
tutobuddy-household-account-model-phase1-plan.md).

States: awaiting_consent → awaiting_name → awaiting_grade → active, plus a
"choosing_learner" micro-state entered by the SWITCH command once a
household has more than one learner. A phone number is a CHANNEL onto an
ACCOUNT (household), never a learner's identity: one account can hold many
LEARNERS, each with independent mastery. Redis session data denormalises
the currently-active learner's id/nickname/grade so per-message handling
stays synchronous (no DB round-trip needed just to read `sess.grade`).

POPIA §34–35: a "competent person" (parent/guardian) must consent before we
process a child's personal information — the consent gate runs before any
profiling or tutoring. Consent is per learner: ADD LEARNER asks again, and
each consent event is a consent_records row (app/orchestrator/consent.py,
docs/guardian-consent-findings.md).
"""

import json

from app.db import get_pool
from app.queue import get_redis

SESSION_TTL_SECONDS = 30 * 24 * 3600

NAME_PROMPT = (
    "Thank you! Consent noted. ✅\n\n"
    "Let's set up your profile 📝 — what should I call you? Just your first "
    "name or a nickname is perfect."
)

NAME_REPROMPT = (
    "I didn't quite catch a name there — just send me a word or two to call "
    "you by. 😊"
)

_RESERVED_NAMES = {"HELP", "RESET", "DELETE", "AGREE", "YES", "ACCEPT", "I AGREE",
                   "ADD LEARNER", "SWITCH"}
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


def switch_prompt(learners: list[dict]) -> str:
    lines = [f"{i}. {l['nickname']} (Grade {l['grade']})" for i, l in enumerate(learners, start=1)]
    return (
        "Who's studying? Reply with a number or a name:\n\n" + "\n".join(lines)
    )


SWITCH_REPROMPT = "I didn't recognise that — reply with one of the numbers or names above. 😊"


def switch_confirmation(name: str, grade: int) -> str:
    return f"Switched to {name} (Grade {grade}). What would you like to work on? 🎓"


def added_learner_welcome(name: str, grade: int) -> str:
    return (
        f"{name} (Grade {grade}) is added to this household! 🎉 You're now "
        f"chatting as {name} — ask a Maths question, or send *SWITCH* to swap "
        f"learners any time."
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
        """The active learner's profile grade. Never defaulted: every tutoring
        reply is pitched at this grade (the grade rule, see
        app.tutor.rag.grade_scoped_context), so a missing grade is a bug to
        surface, not a reason to guess (it used to default to 11)."""
        grade = self.data.get("grade")
        if not grade:
            raise RuntimeError("active learner has no grade in the session")
        return int(grade)

    @property
    def account_id(self) -> int | None:
        return self.data.get("account_id")

    @property
    def guardian_id(self) -> int | None:
        return self.data.get("guardian_id")

    @property
    def active_learner_id(self) -> int | None:
        return self.data.get("active_learner_id")

    @property
    def name(self) -> str:
        return self.data.get("name", "there")


async def load(phone: str) -> Session:
    r = get_redis()
    raw = await r.get(f"sess:{phone}")
    return Session(phone, json.loads(raw) if raw else {})


async def save(sess: Session) -> None:
    r = get_redis()
    await r.set(f"sess:{sess.phone}", json.dumps(sess.data), ex=SESSION_TTL_SECONDS)


async def reset(phone: str) -> None:
    await get_redis().delete(f"sess:{phone}")


# ── Household / learner persistence (Postgres) ──────────────────────────────

async def create_household(phone: str) -> tuple[int, int]:
    """The POPIA consent moment: returns (account_id, guardian_id) for this
    phone's household, creating it if this is truly a new number.

    Idempotent by design: RESET only clears the Redis session, never the
    Postgres account/guardian/learner rows, so a learner who RESETs and
    replies AGREE again must land back on their EXISTING household, not a
    second orphaned one. Reuses the account_channels row (and its oldest
    guardian) for this phone if one already exists."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        account_id = await conn.fetchval(
            "SELECT account_id FROM account_channels WHERE phone = $1", phone
        )
        if account_id is not None:
            guardian_id = await conn.fetchval(
                "SELECT id FROM guardians WHERE account_id = $1 ORDER BY id LIMIT 1",
                account_id,
            )
            if guardian_id is None:
                guardian_id = await conn.fetchval(
                    "INSERT INTO guardians (account_id) VALUES ($1) RETURNING id",
                    account_id,
                )
            return account_id, guardian_id

        account_id = await conn.fetchval(
            "INSERT INTO accounts DEFAULT VALUES RETURNING id"
        )
        await conn.execute(
            "INSERT INTO account_channels (account_id, phone) VALUES ($1, $2)",
            account_id,
            phone,
        )
        guardian_id = await conn.fetchval(
            "INSERT INTO guardians (account_id) VALUES ($1) RETURNING id",
            account_id,
        )
    return account_id, guardian_id


async def account_for_phone(phone: str) -> int | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT account_id FROM account_channels WHERE phone = $1", phone
        )


async def add_learner(
    account_id: int, guardian_id: int, nickname: str, consent_id: int | None = None
) -> int:
    """Creates a learner under an existing household and ties the consent
    event that covers them (consent_records) to the new profile. The
    guardian link carries the time the guardian agreed, not the time the
    profile was created. Returns the new learner_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            learner_id = await conn.fetchval(
                "INSERT INTO learners (account_id, nickname) VALUES ($1, $2) RETURNING id",
                account_id,
                nickname,
            )
            await conn.execute(
                "INSERT INTO guardian_learner (guardian_id, learner_id, consent_given_at) "
                "VALUES ($1, $2, COALESCE("
                "(SELECT consent_at FROM consent_records WHERE id = $3), now()))",
                guardian_id,
                learner_id,
                consent_id,
            )
            await conn.execute(
                "UPDATE consent_records SET learner_id = $2 WHERE id = $1",
                consent_id,
                learner_id,
            )
    return learner_id


async def set_learner_grade(learner_id: int, grade: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE learners SET grade = $2 WHERE id = $1", learner_id, grade
        )


async def list_learners(account_id: int) -> list[dict]:
    """[{id, nickname, grade}, ...] ordered by creation -- used for the
    SWITCH prompt."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, nickname, grade FROM learners WHERE account_id = $1 ORDER BY id",
            account_id,
        )
    return [dict(r) for r in rows]


def match_learner(text: str, learners: list[dict]) -> dict | None:
    """Matches a SWITCH reply against the numbered/named list: a 1-based
    index, or a case-insensitive nickname match."""
    cleaned = text.strip()
    if cleaned.isdigit():
        idx = int(cleaned) - 1
        if 0 <= idx < len(learners):
            return learners[idx]
        return None
    lowered = cleaned.lower()
    for learner in learners:
        if (learner["nickname"] or "").lower() == lowered:
            return learner
    return None


async def delete_active_learner(learner_id: int) -> None:
    """POPIA right to deletion — scoped to ONE learner's profile, not the
    whole household (a sibling's data must not be touched). Deletes this
    learner's conversation_log rows (mastery/attempts/guardian_learner links
    cascade via FK) and the learners row itself.

    Deliberately does NOT touch safeguarding_flags: a self-harm/abuse
    disclosure is a duty-of-care/legal record, not ordinary profile data,
    and is not tied to this table by a foreign key for exactly that reason
    (see the comment on safeguarding_flags in app/db.py)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM conversation_log WHERE learner_id = $1", learner_id
        )
        # llm_calls carries learner_id as a plain value (no FK, so the cost
        # ledger survives schema churn); erase it explicitly. Memory tables
        # (learner_events, learner_lo_mastery, learner_strategy_stats,
        # learners.memory_digest) cascade with the learner row.
        await conn.execute("DELETE FROM llm_calls WHERE learner_id = $1", learner_id)
        await conn.execute("DELETE FROM learners WHERE id = $1", learner_id)


async def delete_household(account_id: int | None, phone: str) -> None:
    """Called when the LAST learner on a household is deleted: erase the
    phone-scoped chat rows (incl. pre-consent rows with no learner_id), the
    account (cascades to account_channels, guardians, guardian_learner) and
    the Redis session. safeguarding_flags are deliberately untouched — see
    the comment on that table in app/db.py."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM conversation_log WHERE phone = $1", phone)
            if account_id is not None:
                await conn.execute("DELETE FROM accounts WHERE id = $1", account_id)
    await reset(phone)
