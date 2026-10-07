"""Processing worker (blueprint §4.2: async, off the webhook path).

Consumes inbound messages from the Redis stream and runs the pipeline:
media (STT/vision) → safety filter → POPIA consent gate → household/learner
profile creation (name + grade) → intent router → RAG-grounded Socratic
reply → send via the WhatsApp adapter.

See tutobuddy-household-account-model-phase1-plan.md: a phone number is a
channel onto an account (household), which can hold multiple learners.
ADD LEARNER and SWITCH let a household with more than one learner add a
sibling or change who's actively chatting.
"""

import asyncio
import json
import logging
import os

import httpx
import redis.asyncio as aioredis

from app.adapters import llm, router, stt
from app.adapters.whatsapp import WhatsAppClient
from app.db import ensure_schema, get_pool
from app.orchestrator import safeguarding, safety, session
from app.queue import GROUP, STREAM, ensure_group, get_redis
from app.tutor.engine import grade_practice_reply, practice_reply, progress_reply, tutor_reply

log = logging.getLogger("katlego.worker")
logging.basicConfig(level=logging.INFO)

HELP_MESSAGE = (
    "Here's what I can do 🎓\n"
    "• Ask me any Maths question — text, 🎤 voice note, or 📸 photo\n"
    "• Say \"quiz me\" (or similar) for a practice question\n"
    "• *SKIP* — drop the current practice question without answering it\n"
    "• *PROGRESS* — see how you're doing this term\n"
    "• *ADD LEARNER* — add a sibling to this household\n"
    "• *SWITCH* — change who's studying\n"
    "• *HELP* — this message\n"
    "• *RESET* — start onboarding again\n"
    "• *DELETE* — erase the active learner's data (POPIA right to deletion)\n\n"
    "Tip: I coach you step by step instead of just giving answers."
)

SMALLTALK_REPLY = (
    "Hey! 👋 Lekker to hear from you. Ready to sharpen those maths skills?\n\n"
    "Send me a question — like _how do I use the quadratic formula?_ — or a "
    "🎤 voice note or 📸 photo of the problem."
)

ADD_LEARNER_NO_SIBLINGS = (
    "It's just you on this account so far! Send *ADD LEARNER* any time to "
    "add a sibling under the same household."
)

ERROR_REPLY = (
    "Eish, something went wrong on my side. 🙈 Please try that again in a moment."
)


def _activate_without_grade(sess, learner: dict) -> None:
    """Make `learner` active but ask for their grade first. Grade rule
    (app.tutor.rag.grade_scoped_context): every reply is pitched at the
    active learner's profile grade, so a profile with no grade must never
    fall back to a default (it used to be silently treated as Grade 11)."""
    sess.data.update(
        state="awaiting_grade",
        active_learner_id=learner["id"],
        grade=None,
        name=learner["nickname"],
        onboarding_reason="add_learner",
    )


async def _send_with_retry(wa: WhatsAppClient, phone: str, body: str) -> None:
    """One retry on a transport error, for messages that must get through
    (the safety referral). Anything else follows the normal error path."""
    try:
        await wa.send_text(phone, body)
    except httpx.TransportError:
        log.warning("send to %s failed, retrying once", phone)
        await asyncio.sleep(1)
        await wa.send_text(phone, body)


async def log_message(
    phone: str,
    direction: str,
    msg_type: str,
    content: str,
    intent: str | None = None,
    flagged: bool = False,
    learner_id: int | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversation_log
                (phone, direction, msg_type, content, intent, flagged, learner_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            phone, direction, msg_type, content[:4000], intent, flagged, learner_id,
        )


async def handle_active(
    wa: WhatsAppClient, sess: session.Session, phone: str, text: str
) -> tuple[str, str]:
    """Returns (reply, intent) for a consented, onboarded learner."""
    command = text.strip().upper()
    if command == "HELP":
        return HELP_MESSAGE, "admin"
    if command == "RESET":
        await session.reset(phone)
        return "Okay, starting fresh! Say hi to begin again. 👋", "admin"
    if command == "ADD LEARNER":
        sess.data.update(state="awaiting_name", onboarding_reason="add_learner")
        await session.save(sess)
        return session.NAME_PROMPT, "admin"
    if command == "SWITCH":
        learners = await session.list_learners(sess.account_id)
        if len(learners) <= 1:
            return ADD_LEARNER_NO_SIBLINGS, "admin"
        sess.data["state"] = "choosing_learner"
        await session.save(sess)
        return session.switch_prompt(learners), "admin"
    if command == "DELETE":
        deleted_name = sess.name
        await session.delete_active_learner(sess.active_learner_id)
        sess.data.pop("pending_practice", None)
        remaining = await session.list_learners(sess.account_id)
        if remaining:
            nxt = remaining[0]
            if not nxt["grade"]:
                # Grade rule: never guess a grade. Ask for it before tutoring.
                _activate_without_grade(sess, nxt)
                await session.save(sess)
                return (
                    f"{deleted_name}'s profile was deleted. ✅ Switched to "
                    f"{nxt['nickname']}.\n\n{session.grade_prompt(nxt['nickname'])}",
                    "admin",
                )
            sess.data.update(
                state="active",
                active_learner_id=nxt["id"],
                grade=nxt["grade"],
                name=nxt["nickname"],
            )
            await session.save(sess)
            return (
                f"{deleted_name}'s profile was deleted. ✅ Switched to "
                f"{nxt['nickname']} (Grade {nxt['grade']}).",
                "admin",
            )
        # Last learner gone → the whole household record goes too (POPIA:
        # "erase everything" must mean everything, incl. the phone number and
        # pre-consent chat rows). Safeguarding flags are kept by design.
        await session.delete_household(sess.account_id, phone)
        sess.data["household_erased"] = True  # in-memory only; Redis was reset
        return (
            f"{deleted_name}'s profile was deleted, and with no learners left "
            f"everything else has been erased too — phone number, consent and "
            f"chat history. ✅\n\nIf you ever want to study together again, just "
            f"say hi; a parent or guardian will need to AGREE again.",
            "admin",
        )
    if command == "PROGRESS":
        return await progress_reply(sess.active_learner_id, sess.grade), "admin"
    if command == "SKIP":
        had_pending = sess.data.pop("pending_practice", None) is not None
        await session.save(sess)
        return (
            "Okay, skipped that one 👍 Say \"quiz me\" whenever you want another."
            if had_pending else
            "No practice question waiting to be skipped — say \"quiz me\" for one.",
            "admin",
        )

    # A practice question is pending (see practice_reply / grade_practice_reply
    # below): the NEXT message from this learner is their attempt at it, not
    # a fresh question — grade it and close the mastery loop, rather than
    # running it through intent classification as if it were a new message.
    pending = sess.data.get("pending_practice")
    if pending:
        sess.data.pop("pending_practice", None)
        reply = await grade_practice_reply(sess.active_learner_id, pending, text)
        await session.save(sess)
        return reply, "quiz_answer"

    intent = await router.classify_intent(text)
    if intent == "smalltalk":
        return SMALLTALK_REPLY, intent
    if intent == "quiz":
        reply, pending = await practice_reply(sess.active_learner_id, sess.grade)
        if pending:
            sess.data["pending_practice"] = pending
            await session.save(sess)
        return reply, intent
    # homework / anything else substantive → the tutor engine
    return await tutor_reply(text, sess.grade, sess.active_learner_id), intent


async def process_job(wa: WhatsAppClient, job: dict) -> None:
    phone = job["from"]
    name = job.get("name") or "learner"
    message = job["message"]
    msg_type = message.get("type", "text")

    sess = await session.load(phone)

    # 1. Extract text (running STT for voice notes first)
    text = ""
    transcript_prefix = ""
    image_bytes: bytes | None = None
    image_mime = ""

    if msg_type == "text":
        text = message.get("text", {}).get("body", "")
    elif msg_type == "audio":
        audio_bytes, mime = await wa.get_media(message["audio"]["id"])
        text = await stt.transcribe(audio_bytes, mime)
        transcript_prefix = f"🎤 I heard: _{text}_\n\n"
    elif msg_type == "image":
        image_bytes, image_mime = await wa.get_media(message["image"]["id"])
        text = message.get("image", {}).get("caption", "")
    else:
        await wa.send_text(phone, "I can read text, 🎤 voice notes and 📸 photos for now!")
        return

    await log_message(
        phone, "inbound", msg_type, safety.redact_pii(text), learner_id=sess.active_learner_id
    )

    # 2. Safety filter — before consent, before intent, always. Categorised
    # (not just a bool) so the safeguarding flag records *why*.
    risk_category = safety.classify_risk(text) if text else None
    if risk_category is not None:
        # Record the flag FIRST. It used to be written after the referral was
        # sent, so a failed send (seen in the test suite: a WhatsApp
        # ConnectTimeout) lost the duty-of-care record entirely and the
        # learner got the generic error message instead of Childline.
        await safeguarding.record_and_notify(
            wa, phone, risk_category, text, learner_id=sess.active_learner_id
        )
        await _send_with_retry(wa, phone, safety.REFERRAL_MESSAGE)
        await log_message(
            phone, "outbound", "system", safety.REFERRAL_MESSAGE, "safety",
            flagged=True, learner_id=sess.active_learner_id,
        )
        return

    # 3. POPIA consent gate + household/learner onboarding state machine
    reply = ""
    intent: str | None = None

    if sess.state == "":
        sess.data = {"state": "awaiting_consent", "name": name}
        await session.save(sess)
        reply = session.CONSENT_MESSAGE
    elif sess.state == "awaiting_consent":
        if text.strip().upper() in {"AGREE", "YES", "ACCEPT", "I AGREE"}:
            account_id, guardian_id = await session.create_household(phone)
            sess.data.update(
                state="awaiting_name",
                account_id=account_id,
                guardian_id=guardian_id,
                onboarding_reason="new_household",
            )
            await session.save(sess)
            reply = session.NAME_PROMPT
        else:
            reply = session.CONSENT_REPROMPT
    elif sess.state == "awaiting_name":
        cleaned = session.clean_name(text)
        if cleaned:
            learner_id = await session.add_learner(sess.account_id, sess.guardian_id, cleaned)
            sess.data.pop("pending_practice", None)
            sess.data.update(state="awaiting_grade", active_learner_id=learner_id, name=cleaned)
            await session.save(sess)
            reply = session.grade_prompt(cleaned)
        else:
            reply = session.NAME_REPROMPT
    elif sess.state == "awaiting_grade":
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits and 8 <= int(digits) <= 12:
            grade = int(digits)
            await session.set_learner_grade(sess.active_learner_id, grade)
            reason = sess.data.get("onboarding_reason", "new_household")
            sess.data.update(state="active", grade=grade)
            await session.save(sess)
            if reason == "add_learner":
                reply = session.added_learner_welcome(sess.name, grade)
            else:
                reply = session.welcome_message(sess.name, grade)
        else:
            reply = session.GRADE_REPROMPT
    elif sess.state == "choosing_learner":
        learners = await session.list_learners(sess.account_id)
        matched = session.match_learner(text, learners)
        if matched and not matched["grade"]:
            # Grade rule: tutoring follows the profile's grade, never a default.
            sess.data.pop("pending_practice", None)
            _activate_without_grade(sess, matched)
            await session.save(sess)
            reply = session.grade_prompt(matched["nickname"])
        elif matched:
            sess.data.pop("pending_practice", None)
            sess.data.update(
                state="active",
                active_learner_id=matched["id"],
                grade=matched["grade"],
                name=matched["nickname"],
            )
            await session.save(sess)
            reply = session.switch_confirmation(matched["nickname"], matched["grade"])
        else:
            reply = session.SWITCH_REPROMPT
    else:  # active
        if image_bytes is not None:
            reply = await llm.photo_reply(image_bytes, image_mime, text, sess.grade)
            intent = "homework"
        else:
            reply, intent = await handle_active(wa, sess, phone, text)

    raw_reply = transcript_prefix + reply
    output_risk = safety.classify_risk(raw_reply)
    if output_risk is not None:
        # Defense-in-depth, not the expected path: the LLM's own generated
        # text tripped the same risk screen a learner disclosure would.
        await safeguarding.record_and_notify(
            wa, phone, f"model_output_{output_risk}", raw_reply,
            learner_id=sess.active_learner_id,
        )
    reply = safety.sanitize_output(raw_reply)
    await wa.send_text(phone, reply)
    if sess.data.get("household_erased"):
        # DELETE of the last learner just erased the account, learner and
        # every conversation_log row for this phone. Logging the confirmation
        # would write a new row for an erased household, and its learner_id
        # no longer exists (FK violation -> the learner also got "Eish, ..."
        # right after the deletion confirmation).
        return
    await log_message(phone, "outbound", "text", reply, intent, learner_id=sess.active_learner_id)


async def main() -> None:
    await ensure_schema()
    await ensure_group()
    r = get_redis()
    wa = WhatsAppClient()
    consumer = os.environ.get("HOSTNAME", "worker-1")
    log.info("worker %s consuming %s", consumer, STREAM)

    while True:
        try:
            entries = await r.xreadgroup(
                GROUP, consumer, {STREAM: ">"}, count=10, block=5000
            )
        except (TimeoutError, aioredis.RedisError) as exc:
            log.warning("redis read failed (%s) — retrying", exc)
            await asyncio.sleep(1)
            continue
        for _, messages in entries or []:
            for entry_id, fields in messages:
                job = None
                try:
                    job = json.loads(fields["payload"])
                    await process_job(wa, job)
                except Exception:
                    log.exception("failed processing %s", entry_id)
                    if job and job.get("from"):
                        try:
                            await wa.send_text(job["from"], ERROR_REPLY)
                        except Exception:
                            log.exception("failed sending error reply")
                finally:
                    await r.xack(STREAM, GROUP, entry_id)


if __name__ == "__main__":
    asyncio.run(main())
