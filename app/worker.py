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
import time

import httpx
import redis.asyncio as aioredis

from app.adapters import ledger, llm, router, stt
from app.adapters.whatsapp import WhatsAppClient
from app.db import ensure_schema, get_pool
from app.orchestrator import consent, practice, safeguarding, safety, session
from app.queue import GROUP, STREAM, ensure_group, get_redis
from app.tutor import diagnostic, memory
from app.tutor.engine import grade_practice_reply, practice_reply, progress_reply, tutor_reply

log = logging.getLogger("katlego.worker")
logging.basicConfig(level=logging.INFO)

HELP_MESSAGE = (
    "Here's what I can do 🎓\n"
    "• Ask me any Maths question — text, 🎤 voice note, or 📸 photo\n"
    "• Say \"quiz me\" (or similar) for a practice question\n"
    "• *SKIP* — drop the current practice question without answering it\n"
    "• *PROGRESS* — see how you're doing this term\n"
    "• *PAPER* — a real past paper, marked against the memo (PAPER <topic> for one topic)\n"
    "• *PREP* — practice for your next test (tell me when it is and what's in it)\n"
    "• *SQUAD* — do a paper with friends and compare marks\n"
    "• *CHECK-IN* — the multiple-choice check-in on every topic in your grade\n"
    "• *REPORT* — your latest check-in summary (for you or a parent)\n"
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

# Mid-conversation "thanks, got it": the full greeting reads as if Katlego
# forgot the chat (week run, 5 Nov). A short close keeps the thread.
SMALLTALK_MID_CHAT = "Pleasure! 🙂 Send me the next one whenever you're ready."



def smalltalk_reply(mem: dict, now: float | None = None) -> str:
    """The greeting on a fresh visit; a short close when the learner is
    mid-session (last turn within the idle window)."""
    turns = mem.get("turns") or []
    recent = bool(turns) and (now or time.time()) - turns[-1].get("at", 0) < memory.IDLE_SECONDS
    return SMALLTALK_MID_CHAT if recent else SMALLTALK_REPLY


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


def start_checkin(sess: session.Session, grade: int) -> str | None:
    """Begin the sign-up check-in for the active learner; returns its intro
    and first question, or None when the grade has no bank (Grade 9)."""
    if not diagnostic.available(grade):
        return None
    sess.data["diagnostic"] = {**diagnostic.start(grade), "learner_id": sess.active_learner_id}
    return diagnostic.intro(sess.name, grade) + "\n\n" + diagnostic.question_text(sess.data["diagnostic"])


async def finish_checkin(sess: session.Session) -> str:
    state = sess.data.pop("diagnostic")
    res = diagnostic.results(state)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            focus = diagnostic.focus(res, await diagnostic.topic_weights(conn, state["grade"]))
            await diagnostic.save(conn, sess.active_learner_id, state, res, focus)
    return diagnostic.report(sess.name, state["grade"], res, focus)


async def handle_checkin(sess: session.Session, text: str) -> str | None:
    """The check-in's turn, or None when this message isn't an answer
    (then the check-in pauses and the message is handled as usual)."""
    state = sess.data["diagnostic"]
    letter = diagnostic.parse_answer(text, diagnostic.current(state))
    if letter is None:
        state["paused"] = True
        await session.save(sess)
        return None
    diagnostic.answer(state, letter)
    if diagnostic.finished(state):
        reply = await finish_checkin(sess)
    else:
        reply = diagnostic.question_text(state)
    await session.save(sess)
    return reply


def checkin_paused_note(sess: session.Session) -> str:
    st = sess.data["diagnostic"]
    done = sum(1 for q in st["queue"][:st["i"]] if q.endswith("-core"))
    return f"\n\n⏸️ Check-in paused at {done}/{st['topics']}. Send CHECK-IN to carry on."


async def handle_active(
    wa: WhatsAppClient, sess: session.Session, phone: str, text: str
) -> tuple[str, str]:
    """Returns (reply, intent) for a consented, onboarded learner."""
    command = text.strip().upper()
    st = sess.data.get("diagnostic")
    if st and (st.get("learner_id") != sess.active_learner_id or st["grade"] != sess.grade):
        sess.data.pop("diagnostic")  # a sibling's check-in, or the grade changed
        await session.save(sess)
    if command in ("CHECK-IN", "CHECKIN", "CHECK IN"):
        st = sess.data.get("diagnostic")
        if st:
            st["paused"] = False
            await session.save(sess)
            return "Carrying on with your check-in 👍\n\n" + diagnostic.question_text(st), "checkin"
        first = start_checkin(sess, sess.grade)
        if first is None:
            return ("The check-in isn't ready for Grade 9 yet. Ask me anything, or say \"quiz me\".",
                    "checkin")
        await session.save(sess)
        return first, "checkin"
    if command == "PAUSE" and sess.data.get("diagnostic"):
        sess.data["diagnostic"]["paused"] = True
        await session.save(sess)
        return "Check-in paused ⏸️ Send CHECK-IN whenever you want to carry on.", "checkin"
    if command == "REPORT":
        pool = await get_pool()
        async with pool.acquire() as conn:
            last = await diagnostic.latest(conn, sess.active_learner_id)
        if not last:
            return ("No check-in yet. Send CHECK-IN to do one (about 15 minutes), then REPORT "
                    "shows the summary.", "admin")
        return diagnostic.report(sess.name, last["grade"], last, last["focus"]), "admin"
    st = sess.data.get("diagnostic")
    if st and not st.get("paused") and command not in ("HELP", "RESET", "ADD LEARNER", "SWITCH",
                                                        "DELETE", "PROGRESS", "SKIP"):
        reply = await handle_checkin(sess, text)
        if reply is not None:
            return reply, "checkin"
        reply, intent = await handle_active(wa, sess, phone, text)
        if sess.data.get("diagnostic"):
            reply += checkin_paused_note(sess)
        return reply, intent
    # Past papers, test prep and study squads (app/orchestrator/practice.py).
    # Before HELP/SKIP: inside a paper those words mean "help with this
    # question" and "skip this question".
    handled = await practice.handle(sess, text, tutor_reply)
    if handled:
        return handled
    if command == "HELP":
        return HELP_MESSAGE, "admin"
    if command == "RESET":
        await memory.forget(sess.active_learner_id)
        await session.reset(phone)
        return "Okay, starting fresh! Say hi to begin again. 👋", "admin"
    if command == "ADD LEARNER":
        # Consent is per learner: a sibling needs the guardian to agree again.
        sess.data.update(state="awaiting_consent", onboarding_reason="add_learner")
        await session.save(sess)
        return consent.notice("add_learner"), "consent_notice"
    if command == "SWITCH":
        learners = await session.list_learners(sess.account_id)
        if len(learners) <= 1:
            return ADD_LEARNER_NO_SIBLINGS, "admin"
        sess.data["state"] = "choosing_learner"
        await session.save(sess)
        return session.switch_prompt(learners), "admin"
    if command == "DELETE":
        deleted_name = sess.name
        await memory.forget(sess.active_learner_id)
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

    # A short reply to the problem we're already working on ("minus 5?",
    # "x = 4") goes straight back to the tutor: the router would see it out
    # of context (and might call it smalltalk), and skipping it saves a call.
    mem = await memory.load(sess.active_learner_id)
    if memory.continues_problem(mem, text):
        return await tutor_reply(text, sess.grade, sess.active_learner_id, sess.name), "homework"

    intent = await router.classify_intent(text)
    if intent == "smalltalk":
        return smalltalk_reply(mem), intent
    if intent == "quiz":
        reply, pending = await practice_reply(sess.active_learner_id, sess.grade)
        if pending:
            sess.data["pending_practice"] = pending
            await session.save(sess)
        return reply, intent
    # homework / anything else substantive → the tutor engine
    return await tutor_reply(text, sess.grade, sess.active_learner_id, sess.name), intent


async def process_job(wa: WhatsAppClient, job: dict) -> None:
    phone = job["from"]
    name = job.get("name") or "learner"
    message = job["message"]
    msg_type = message.get("type", "text")

    sess = await session.load(phone)
    # Jobs run one after another in one task: reset per-job ledger context so
    # one learner's id/strategy can never be written onto another's calls.
    ledger.current_learner.set(sess.data.get("active_learner_id"))
    ledger.current_strategy.set(None)
    ledger.last_call_id.set(None)

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
        reply, intent = consent.notice(), "consent_notice"
    elif sess.state == "awaiting_consent":
        reason = sess.data.get("onboarding_reason", "new_household")
        code = consent.school_code(text)
        school = await consent.redeem_school_code(code) if code else None
        if consent.agreed(text) or school:
            # create_household is idempotent: a sibling lands on the same account.
            account_id, guardian_id = await session.create_household(phone)
            if school:
                # The school holds the signed slip; the code stands for it.
                consent_id = await consent.record(
                    account_id, method="school_code", level="school", replied_from=phone,
                    message=message, notice={"version": school["slip_version"]},
                    reply_text=code, school_code=code,
                )
            else:
                consent_id = await consent.record(
                    account_id, method="typed_agree", level="declared", replied_from=phone,
                    message=message, notice=sess.data.get("notice"), reply_text=text,
                )
            sess.data.update(
                state="awaiting_name",
                account_id=account_id,
                guardian_id=guardian_id,
                onboarding_reason=reason,
                consent_id=consent_id,
            )
            await session.save(sess)
            reply = session.NAME_PROMPT
        elif reason == "add_learner" and text.strip().upper() == "CANCEL":
            # Back to the learner who was studying; nobody was added.
            sess.data.pop("onboarding_reason", None)
            sess.data["state"] = "active"
            await session.save(sess)
            reply = f"Okay, no learner added. Carrying on with {sess.name}. 🎓"
        elif code:
            reply = consent.BAD_SCHOOL_CODE
        else:
            reply = consent.reprompt(reason)
    elif sess.state == "awaiting_name":
        cleaned = session.clean_name(text)
        if cleaned:
            learner_id = await session.add_learner(
                sess.account_id, sess.guardian_id, cleaned, sess.data.pop("consent_id", None)
            )
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
            # Sign-up check-in (app/tutor/diagnostic.py): straight after the grade.
            first = start_checkin(sess, grade)
            if first:
                await session.save(sess)
                reply += "\n\n" + first
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

    notice_text = reply if intent == "consent_notice" else None
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
    sent = await wa.send_text(phone, reply)
    if notice_text:
        # Remember which wording is on screen and its WhatsApp id, so the
        # consent record can point at exactly what the guardian agreed to.
        sess.data["notice"] = await consent.notice_sent(safety.sanitize_output(notice_text), sent)
        await session.save(sess)
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
