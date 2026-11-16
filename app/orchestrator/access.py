"""Access gate: closed-pilot access codes and the investor demo code.

Runs in the worker after the safety filter (duty of care comes first, for
everyone) and before the POPIA consent gate. A phone number needs an active
grant to reach Katlego. A grant comes from redeeming a code:

- pilot codes: for learners, schools and NGOs in the closed pilot. Usually
  single use, valid for N days from redemption.
- demo codes: for investors and partners (adults). Multi-use, short access,
  adult consent wording, and the data is erased after the demo period
  (python -m app.access_admin purge-demo, run daily by cron on the server).

Codes are matched anywhere in the message, ignoring case, spaces and dashes,
so a prefilled wa.me link ("Hi Katlego, my code is TB-7KQ4-M2XP") works.

Off unless ACCESS_GATE=on, so local runs and the E2E suite behave as before.
ACCESS_ADMIN_PHONES (comma-separated wa_ids) always pass.

Prices are not set yet, so nothing here mentions payment. When paid plans
arrive, a payment confirmation simply creates a grant the same way.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import secrets
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.db import get_pool

SAST = ZoneInfo("Africa/Johannesburg")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
MAX_FAILED_PER_DAY = 5
SCHEMA_LOCK = 72_210_017  # advisory lock key, distinct from app.db's

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_codes (
    code_norm   text PRIMARY KEY,           -- uppercase letters/digits only
    code        text NOT NULL,              -- as printed, e.g. TB-7KQ4-M2XP
    kind        text NOT NULL CHECK (kind IN ('pilot', 'demo')),
    label       text NOT NULL DEFAULT '',   -- who it was issued to
    days        int  NOT NULL CHECK (days > 0),
    max_uses    int  NOT NULL DEFAULT 1 CHECK (max_uses > 0),
    uses        int  NOT NULL DEFAULT 0,
    valid_until timestamptz,                -- last day the code can be redeemed
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);
-- One row per phone number: its current access window.
CREATE TABLE IF NOT EXISTS access_grants (
    phone        text PRIMARY KEY,
    code_norm    text REFERENCES access_codes(code_norm) ON DELETE SET NULL,
    kind         text NOT NULL CHECK (kind IN ('pilot', 'demo', 'manual')),
    granted_at   timestamptz NOT NULL DEFAULT now(),
    access_until timestamptz NOT NULL,
    reminded_at  timestamptz
);
-- Waiting list and code-guessing throttle. Phone number only: no names or
-- schools are asked for before a parent or guardian has consented (POPIA).
CREATE TABLE IF NOT EXISTS access_requests (
    phone           text PRIMARY KEY,
    first_seen      timestamptz NOT NULL DEFAULT now(),
    last_seen       timestamptz NOT NULL DEFAULT now(),
    joined_at       timestamptz,
    failed_attempts int NOT NULL DEFAULT 0,
    failed_since    timestamptz
);
"""

# ── Messages (Katlego's voice) ──────────────────────────────────────────────

GATE_MESSAGE = (
    "Hi! I'm *Katlego* 🎓, TutoBuddy's maths study buddy on WhatsApp.\n\n"
    "We're running a small pilot right now, so I can only chat with people "
    "who have an access code.\n\n"
    "• Have a code? Send it here.\n"
    "• Don't have one yet? Reply *JOIN* to go on the waiting list.\n\n"
    "Parents, schools and partners can find out more at tutobuddy.africa"
)
JOIN_REPLY = (
    "Thanks! 🙌 You're on the TutoBuddy waiting list. We'll send you an access "
    "code on WhatsApp when a pilot place opens. You don't need to send anything "
    "else.\n\nReply *DELETE* any time to take this number off the list."
)
CODE_NOT_RECOGNISED = (
    "Hmm, I don't recognise that code. 🤔 Please check it and send it again, "
    "exactly as you received it.\n\nNo code yet? Reply *JOIN* to go on the waiting list."
)
CODE_EXPIRED = (
    "That code has expired. Reply *JOIN* and the TutoBuddy team will get a new "
    "one to you."
)
CODE_USED_UP = (
    "That code has already been used as many times as it allows. Reply *JOIN* "
    "and the TutoBuddy team will get a new one to you."
)
TOO_MANY_TRIES = (
    "That's a lot of code attempts for one day. Please try again tomorrow, or "
    "reply *JOIN* to go on the waiting list."
)
REQUEST_DELETED = "Done. This number is off the TutoBuddy waiting list. 👋"


def code_accepted(kind: str, until: dt.datetime) -> str:
    if kind == "demo":
        return (
            f"✅ Demo code accepted. Thanks for trying Katlego! Your demo access "
            f"is open until *{fmt_date(until)}*."
        )
    return f"✅ Code accepted! Your TutoBuddy pilot access is open until *{fmt_date(until)}*."


def already_active(until: dt.datetime) -> str:
    return f"Your access is already open until *{fmt_date(until)}*. 🙂"


def access_ended(until: dt.datetime) -> str:
    return (
        f"Your TutoBuddy access ended on *{fmt_date(until)}*. Your progress is "
        "saved. To keep going, send a new access code, or reply *JOIN* and the "
        "team will get back to you."
    )


DEMO_CONSENT_MESSAGE = (
    "Before we start: this is a *demo* for adults (18+) who want to see how "
    "Katlego tutors learners. 🎓\n\n"
    "_For the demo, Katlego stores this phone number, a nickname, the grade you "
    "pick and your demo chats, so it can personalise the session the way it "
    "would for a learner. Demo data is used only to run the demo, is never sold "
    "or shared, and is erased after the demo period. Send DELETE any time to "
    "erase it sooner._\n\n"
    "Reply *AGREE* to confirm you're 18 or older and happy to continue. (For "
    "real learners, a parent or guardian gives this consent.)"
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def enabled() -> bool:
    return os.environ.get("ACCESS_GATE", "off").strip().lower() in ("on", "1", "true", "yes")


def admin_phones() -> set[str]:
    return {normalize_phone(p) for p in os.environ.get("ACCESS_ADMIN_PHONES", "").split(",") if p.strip()}


def normalize(text: str) -> str:
    """Uppercase letters and digits only: 'tb-7kq4 m2xp' -> 'TB7KQ4M2XP'."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def normalize_phone(phone: str) -> str:
    """wa_id form: digits only, a South African 0XXXXXXXXX becomes 27XXXXXXXXX."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "27" + digits[1:]
    return digits


_CODE_LIKE = re.compile(r"^(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{6,24}$")


def looks_like_code(text: str) -> bool:
    """A short message that is one code-shaped token (letters AND digits),
    e.g. 'TB-7KQ4-M2XP'. Used only to decide between 'code not recognised'
    and the general welcome; maths like '2x+5=13' has symbols and fails."""
    t = (text or "").strip().upper()
    if " " in t:
        tokens = t.split()
        if len(tokens) > 3:
            return False
        t = "-".join(tokens)
    return bool(_CODE_LIKE.match(t))


def new_code(prefix: str = "TB", groups: int = 2, size: int = 4) -> str:
    parts = ["".join(secrets.choice(CODE_ALPHABET) for _ in range(size)) for _ in range(groups)]
    return "-".join([prefix, *parts]) if prefix else "-".join(parts)


def fmt_date(ts: dt.datetime) -> str:
    return ts.astimezone(SAST).strftime("%-d %b %Y")


@dataclass
class Gate:
    allowed: bool
    reply: str | None = None   # alone when not allowed; a prefix when just_granted
    kind: str | None = None    # pilot | demo | manual | admin, for an allowed number
    just_granted: bool = False


_schema_ready = False


async def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", SCHEMA_LOCK)
            await conn.execute(SCHEMA)
    _schema_ready = True


# ── The gate ────────────────────────────────────────────────────────────────


async def check(phone: str, text: str) -> Gate:
    if not enabled():
        return Gate(True)
    if normalize_phone(phone) in admin_phones():
        return Gate(True, kind="admin")
    await ensure_schema()

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            now = await conn.fetchval("SELECT now()")
            grant = await conn.fetchrow(
                "SELECT * FROM access_grants WHERE phone = $1 FOR UPDATE", phone
            )
            req = await conn.fetchrow(
                "SELECT * FROM access_requests WHERE phone = $1 FOR UPDATE", phone
            )
            failed = 0
            if req and req["failed_since"] and now - req["failed_since"] < dt.timedelta(days=1):
                failed = req["failed_attempts"]
            throttled = failed >= MAX_FAILED_PER_DAY

            # 1. A code anywhere in the message (short messages only).
            norm = normalize(text)
            code = None
            if norm and len(text) <= 300 and not throttled:
                code = await conn.fetchrow(
                    """SELECT * FROM access_codes
                       WHERE active AND strpos($1, code_norm) > 0
                       ORDER BY length(code_norm) DESC LIMIT 1
                       FOR UPDATE""",
                    norm,
                )
            if code is not None:
                return await _redeem(conn, phone, now, code, grant)

            # 2. An open grant.
            if grant and grant["access_until"] > now:
                return Gate(True, kind=grant["kind"])

            # 3. No access: waiting list, DELETE, wrong code, or the welcome.
            command = text.strip().upper()
            if command == "DELETE":
                await conn.execute("DELETE FROM access_requests WHERE phone = $1", phone)
                return Gate(False, REQUEST_DELETED)

            await conn.execute(
                """INSERT INTO access_requests (phone) VALUES ($1)
                   ON CONFLICT (phone) DO UPDATE SET last_seen = now()""",
                phone,
            )
            if command == "JOIN" or command.startswith("JOIN "):
                await conn.execute(
                    "UPDATE access_requests SET joined_at = coalesce(joined_at, now()) WHERE phone = $1",
                    phone,
                )
                return Gate(False, JOIN_REPLY)
            if throttled:
                return Gate(False, TOO_MANY_TRIES)
            if looks_like_code(text):
                await conn.execute(
                    """UPDATE access_requests
                       SET failed_attempts = CASE WHEN failed_since IS NULL
                                OR now() - failed_since >= interval '1 day' THEN 1
                                ELSE failed_attempts + 1 END,
                           failed_since = CASE WHEN failed_since IS NULL
                                OR now() - failed_since >= interval '1 day' THEN now()
                                ELSE failed_since END
                       WHERE phone = $1""",
                    phone,
                )
                return Gate(False, CODE_NOT_RECOGNISED)
            if grant:
                return Gate(False, access_ended(grant["access_until"]))
            return Gate(False, GATE_MESSAGE)


async def _redeem(conn, phone: str, now: dt.datetime, code, grant) -> Gate:
    if code["valid_until"] is not None and code["valid_until"] < now:
        return Gate(False, CODE_EXPIRED)
    same_code_open = (
        grant is not None
        and grant["code_norm"] == code["code_norm"]
        and grant["access_until"] > now
    )
    if same_code_open:
        return Gate(True, already_active(grant["access_until"]), grant["kind"], just_granted=True)
    if code["uses"] >= code["max_uses"]:
        if grant and grant["access_until"] > now:
            return Gate(True, kind=grant["kind"])  # someone else's code; they already have access
        return Gate(False, CODE_USED_UP)

    start = max(now, grant["access_until"]) if grant else now
    until = start + dt.timedelta(days=code["days"])
    await conn.execute(
        """INSERT INTO access_grants (phone, code_norm, kind, access_until)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (phone) DO UPDATE SET code_norm = EXCLUDED.code_norm,
               kind = EXCLUDED.kind, granted_at = now(),
               access_until = EXCLUDED.access_until, reminded_at = NULL""",
        phone, code["code_norm"], code["kind"], until,
    )
    await conn.execute(
        "UPDATE access_codes SET uses = uses + 1 WHERE code_norm = $1", code["code_norm"]
    )
    await conn.execute(
        "UPDATE access_requests SET failed_attempts = 0, failed_since = NULL WHERE phone = $1", phone
    )
    return Gate(True, code_accepted(code["kind"], until), code["kind"], just_granted=True)
