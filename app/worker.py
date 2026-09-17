"""Processing worker (blueprint §4.2: async, off the webhook path).

Consumes inbound messages from the Redis stream and runs the pipeline:
media (STT/vision) → safety filter → POPIA consent gate → intent router →
RAG-grounded Socratic reply → send via the WhatsApp adapter.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from app.adapters import llm, stt
from app.adapters.whatsapp import WhatsAppClient
from app.db import ensure_schema, get_pool
from app.orchestrator import safeguarding, safety, session
from app.queue import GROUP, STREAM, ensure_group, get_redis
from app.tutor.engine import practice_reply, progress_reply, tutor_reply

log = logging.getLogger("katlego.worker")
logging.basicConfig(level=logging.INFO)

HELP_MESSAGE = (
    "Here's what I can do 🎓\n"
    "• Ask me any Maths question — text, 🎤 voice note, or 📸 photo\n"
    "• Say \"quiz me\" (or similar) for a practice question\n"
    "• *PROGRESS* — see how you're doing this term\n"
    "• *HELP* — this message\n"
    "• *RESET* — start onboarding again\n"
    "• *DELETE* — erase all your data (POPIA right to deletion)\n\n"
    "Tip: I coach you step by step instead of just giving answers."
)

SMALLTALK_REPLY = (
    "Hey! 👋 Lekker to hear from you. Ready to sharpen those maths skills?\n\n"
    "Send me a question — like _how do I use the quadratic formula?_ — or a "
    "🎤 voice note or 📸 photo of the problem."
)

DELETE_CONFIRMATION = (
    "All your data has been deleted — profile, progress and chat history. ✅\n"
    "If you ever want to study together again, just say hi."
)

ERROR_REPLY = (
    "Eish, something went wrong on my side. 🙈 Please try that again in a moment."
)


async def log_message(
    phone: str,
    direction: str,
    msg_type: str,
    content: str,
    intent: str | None = None,
    flagged: bool = False,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversation_log (phone, direction, msg_type, content, intent, flagged)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            phone, direction, msg_type, content[:4000], intent, flagged,
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
    if command == "DELETE":
        await session.delete_learner(phone)
        return DELETE_CONFIRMATION, "admin"
    if command == "PROGRESS":
        return await progress_reply(phone, sess.grade), "admin"

    intent = await llm.classify_intent(text)
    if intent == "smalltalk":
        return SMALLTALK_REPLY, intent
    if intent == "quiz":
        return await practice_reply(phone, sess.grade), intent
    # homework / anything else substantive → the tutor engine
    return await tutor_reply(text, sess.grade), intent


async def process_job(wa: WhatsAppClient, job: dict) -> None:
    phone = job["from"]
    name = job.get("name") or "learner"
    message = job["message"]
    msg_type = message.get("type", "text")

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

    await log_message(phone, "inbound", msg_type, safety.redact_pii(text))

    # 2. Safety filter — before consent, before intent, always. Categorised
    # (not just a bool) so the safeguarding flag records *why*.
    risk_category = safety.classify_risk(text) if text else None
    if risk_category is not None:
        await wa.send_text(phone, safety.REFERRAL_MESSAGE)
        await log_message(phone, "outbound", "system", safety.REFERRAL_MESSAGE, "safety", flagged=True)
        await safeguarding.record_and_notify(wa, phone, risk_category, text)
        return

    # 3. POPIA consent gate + onboarding state machine
    sess = await session.load(phone)
    reply = ""
    intent: str | None = None

    if sess.state == "":
        sess.data = {"state": "awaiting_consent", "name": name}
        await session.save(sess)
        reply = session.CONSENT_MESSAGE
    elif sess.state == "awaiting_consent":
        if text.strip().upper() in {"AGREE", "YES", "ACCEPT", "I AGREE"}:
            await session.record_consent(phone, sess.data.get("name", name))
            sess.data["state"] = "awaiting_grade"
            await session.save(sess)
            reply = session.GRADE_PROMPT
        else:
            reply = session.CONSENT_REPROMPT
    elif sess.state == "awaiting_grade":
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits and 8 <= int(digits) <= 12:
            grade = int(digits)
            await session.record_grade(phone, grade)
            sess.data.update(state="active", grade=grade)
            await session.save(sess)
            reply = session.welcome_message(grade)
        else:
            reply = session.GRADE_REPROMPT
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
            wa, phone, f"model_output_{output_risk}", raw_reply
        )
    reply = safety.sanitize_output(raw_reply)
    await wa.send_text(phone, reply)
    await log_message(phone, "outbound", "text", reply, intent)


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
