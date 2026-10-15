"""Tutor engine: retrieve grounded context, then reply Socratically —
plus term-progress reporting and practice-question generation, both grounded
in learner_topic_mastery / topics (see app.tutor.rag)."""

import datetime
import logging
import random

from app.adapters import ledger, llm
from app.db import get_pool
from app.tutor import mastery, memory, pedagogy, prompts
from app.tutor.state import parse_state, parse_turn, strip_state
from app.tutor.rag import (
    get_past_paper_excerpts,
    get_term_progress,
    grade_scoped_context,
    term_focus_for,
    pick_practice_topic,
    record_practice_attempt,
    retrieve,
)

DEFAULT_SUBJECT = "Mathematics"


log = logging.getLogger("katlego.engine")

# What the last tutor_reply decided and observed, for evals (the bench's
# conversations suite reads it; production never does).
import contextvars  # noqa: E402

last_turn: contextvars.ContextVar[dict | None] = contextvars.ContextVar("last_turn", default=None)


async def tutor_reply(question: str, grade: int, learner_id: int | None = None,
                      name: str | None = None) -> str:
    """One tutoring turn with memory, mastery and pedagogy (spec v0.1,
    steps 1-3). Still exactly ONE LLM call per turn.

      1. load this learner's memory (Redis, 5-turn window)
      2. retrieve own-grade CAPS notes (grade rule unchanged); map them to a
         curriculum topic; a reply to the working problem keeps its topic
      3. pedagogy.choose(): strategy + hint + reveal, decided in code
      4. one Socratic call; the reply ends with a STATE line
      5. strip + validate STATE; write evidence -> LO/topic mastery;
         credit/debit the strategy that prompted this message
      6. record the turn; consolidate the window every 5 turns / on a
         topic change (code-built digest, persisted)

    `grade` is the active learner's profile grade. Only that grade's CAPS
    extracts reach the model (rag.grade_scoped_context); a question about
    another grade's topic is named, not taught, and records no evidence."""
    if learner_id is None:  # eval/legacy callers: the stateless path
        ctx = await grade_scoped_context(question, grade)
        return strip_state(await llm.socratic_reply(
            question, ctx["chunks"], grade, above=ctx["above"],
            grade_topics=ctx["grade_topics"]))[0]

    ledger.current_learner.set(learner_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        mem = await memory.load(learner_id, await memory.load_history(conn, learner_id))
    continuing = memory.continues_problem(mem, question)

    # A reply like "x = 6" retrieves nothing useful on its own; search with
    # the working problem attached so the notes stay on topic.
    query = f"{mem['working']['problem']} {question}" if continuing else question
    ctx = await grade_scoped_context(query, grade)
    term_focus = None
    if ctx["above"]:
        term_focus = await term_focus_for(learner_id, grade, current_term())

    async with pool.acquire() as conn:
        topic = None
        if not ctx["above"]:
            if continuing and mem["working"]["topic_id"]:
                topic = {"id": mem["working"]["topic_id"], "name": mem["working"]["topic"]}
            else:
                topic = await mastery.resolve_topic(
                    conn, grade, [c["topic"] for c in ctx["chunks"]], mem["working"]["topic_id"])
        los = await mastery.lo_candidates(
            conn, topic["id"], query=query, keep_code=mem["working"]["lo_code"]) if topic else []
        miscs = await mastery.misconception_codes(conn, topic["id"] if topic else None)
        stats = await pedagogy.load_stats(conn, learner_id, topic["id"]) if topic else {}
        # The objective in play: the working one when continuing, else the
        # best match for this question.
        focus = (next((lo for lo in los if lo["code"] == mem["working"]["lo_code"]), None)
                 if continuing else None) or (los[0] if los else None)
        lo_score = await conn.fetchval(
            "SELECT mastery_score FROM learner_lo_mastery WHERE learner_id = $1 AND lo_id = $2",
            learner_id, focus["id"]) if focus else None
        lo_score = float(lo_score) if lo_score is not None else None
        review = None
        if memory.is_new_session(mem):
            review = await conn.fetchrow(
                """
                SELECT lo.objective_code AS code, lo.objective, m.mastery_score AS score
                FROM learner_lo_mastery m JOIN learning_objectives lo ON lo.id = m.lo_id
                WHERE m.learner_id = $1 AND m.next_review_at < now()
                ORDER BY m.next_review_at LIMIT 1
                """, learner_id)
            review = ({**dict(review), "score": float(review["score"])} if review else None)

    w = mem["working"]
    lo_code = focus["code"] if focus else None
    # A new question starts a new problem: its decision must not inherit the
    # previous problem's failures, tried strategies or answer requests.
    new_problem = not continuing
    decision = pedagogy.with_fallback(dict(
        score=lo_score if lo_score is not None else mastery.MASTERY_START,
        current=w["strategy"],
        fails_in_row=0 if new_problem else w["fails_in_row"],
        tried_on_problem=[] if new_problem else w["tried"],
        new_lo_this_session=bool(lo_code) and lo_code not in mem["los_seen"] and lo_score is None,
        misconception_repeated=len(w["misc_recent"]) != len(set(w["misc_recent"])),
        review_due=review is not None,
        has_open_problem=continuing,
        asked_answer_count=(0 if new_problem else w["asked_answer"])
                           + int(memory.asks_for_answer(question)),
        wrong_on_problem=0 if new_problem else w["wrong_on_problem"],
        stats=stats,
        rng=random.Random(f"{learner_id}:{mem['session_turns']}"),
    ))
    ledger.current_strategy.set(decision["strategy"])

    raw = await llm.socratic_reply(
        question, ctx["chunks"], grade, above=ctx["above"],
        # Topic list only when it's needed to judge an off-grade question
        # (saves ~200 prompt tokens on most turns).
        grade_topics=ctx["grade_topics"] if (ctx["above"] or not ctx["chunks"]) else None,
        term_focus=term_focus,
        memory_block=memory.prompt_block(mem, name=name, grade=grade, lo_score=lo_score,
                                         review=review),
        pedagogy=decision, lo_candidates=los, misconceptions=miscs, continuing=continuing,
    )
    reply, body, parsed_as = parse_turn(raw)
    if not reply.strip():
        # Unparseable JSON with no recoverable reply: never send raw output.
        raise RuntimeError("tutor_reply: model output had no usable reply")
    mode = llm.last_output_mode.get()
    if mode == "json" and parsed_as != "json":
        mode = f"json_failed:{parsed_as}"
    state = parse_state(
        body,
        lo_codes={lo["code"] for lo in los},
        misconception_codes={m["code"] for m in miscs},
        strategies=set(pedagogy.STRATEGIES),
    )
    await ledger.mark_state(ledger.last_call_id.get(), bool(state and state["valid"]), mode)
    if state is None:
        log.info("tutor_reply: no usable STATE line (learner %s)", learner_id)

    used = (state or {}).get("strategy") or decision["strategy"]
    ev = (state or {}).get("ev", "none")
    # `ev` judges the learner's message, which answered the PREVIOUS reply:
    # credit that reply's strategy, hint level and topic, not this one's.
    prev_strategy, prev_hint, prev_topic = w["strategy"], w.get("last_hint", 0), w["topic_id"]
    ev_topic_id = prev_topic if (continuing and prev_topic) else (topic["id"] if topic else None)
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                if ev_topic_id and ev != "none":
                    lo_id = next((lo["id"] for lo in los
                                  if lo["code"] == state.get("lo") and ev_topic_id == (topic or {}).get("id")),
                                 None)
                    await mastery.record_event(
                        conn, learner_id, ev_topic_id, source="chat", evidence=ev,
                        lo_id=lo_id, hint_level=prev_hint, strategy=prev_strategy or used,
                        misconception=state.get("misc"))
                ok = pedagogy.outcome(ev)
                if prev_topic and prev_strategy and ok is not None:
                    await pedagogy.record_outcome(conn, learner_id, prev_topic, prev_strategy, ok)
        except ValueError:
            log.warning("grade rule: evidence on topic %s refused", ev_topic_id)
        except Exception:  # noqa: BLE001 -- bookkeeping never costs the learner their reply
            log.exception("tutor_reply: evidence write failed (learner %s)", learner_id)

        consolidate_now = memory.record_turn(mem, question, reply, state, topic, used,
                                             new_problem=new_problem)
        if consolidate_now:
            memory.consolidate(mem)
            mem["_persist"] = True
        if mem.pop("_persist", False):
            await memory.persist_digest(conn, mem)
    if decision.get("restart"):
        mem["working"].update(tried=[], fails_in_row=0, wrong_on_problem=0)
    await memory.save(mem)
    last_turn.set({"decision": decision, "state": state, "topic": topic, "output_mode": mode,
                   "continuing": continuing, "problem": mem["working"]["problem"],
                   "lo_score": lo_score})
    return reply


async def eval_answer(question: str, grade: int) -> str:
    """Direct worked answer for the eval harness (never sent to learners)."""
    chunks = await retrieve(question, grade)
    return await llm.direct_answer(question, chunks, grade)


def current_term() -> int:
    """South African school-year term from today's date — a rough calendar
    mapping (Term 1 Jan-Mar, Term 2 Apr-Jun, Term 3 Jul-Sep, Term 4 Oct-Dec),
    not the real gazetted term dates (which shift year to year). Good enough
    until real ATP dates (atp_schedules) are loaded; callers can always pass
    an explicit term instead."""
    month = datetime.date.today().month
    return min(4, (month - 1) // 3 + 1)


async def progress_reply(
    learner_id: int, grade: int, term: int | None = None, subject: str = DEFAULT_SUBJECT
) -> str:
    """Term-progress message for the learner. Pure data formatting under the
    hood (prompts.progress_message) — no LLM call, so nothing here can be
    hallucinated. `learner_id` identifies the individual learner within a
    household (see tutobuddy-household-account-model-phase1-plan.md), not
    a phone number -- a phone may have several learners behind it."""
    resolved = term or current_term()
    progress = await get_term_progress(learner_id, grade, resolved, subject)
    pool = await get_pool()
    async with pool.acquire() as conn:
        objectives = await mastery.objective_progress(
            conn, learner_id, [t["topic_id"] for t in progress["topics"]], resolved)
    return prompts.progress_message(progress, objectives)


async def practice_reply(
    learner_id: int, grade: int, term: int | None = None, subject: str = DEFAULT_SUBJECT
) -> tuple[str, dict | None]:
    """Picks the learner's weakest/least-assessed topic this term (heavily-
    weighted-and-weak first, see rag.get_term_progress), pulls past-paper
    excerpts for style/topic reference only, and has the LLM write and solve
    an original practice question — never quoting the OCR'd excerpts as
    ground truth (see prompts.practice_system).

    Returns (reply_text, pending) where `pending` is what the caller
    (app.worker.handle_active) must stash on the session so the learner's
    NEXT message can be recognised as their answer and graded — see
    grade_practice_reply below. `pending` is None when no question was set
    (e.g. no topics loaded for this grade/term yet)."""
    resolved_term = term or current_term()
    progress = await get_term_progress(learner_id, grade, resolved_term, subject)
    topic = await pick_practice_topic(progress)
    if topic is None:
        return (
            f"I don't have Term {resolved_term} {subject} topics loaded for "
            f"Grade {grade} yet 📚 Ask me a question instead and we'll work "
            f"through it together.",
            None,
        )
    excerpts = await get_past_paper_excerpts(topic["topic"], grade)
    result = await llm.practice_question(topic["topic"], grade, topic.get("band"), excerpts)
    pending = {
        "topic_id": topic["topic_id"],
        "topic": topic["topic"],
        "question": result["question"],
        "model_answer": result.get("model_answer"),
        "grade": grade,
    }
    return result["question"], pending


async def grade_practice_reply(learner_id: int, pending: dict, learner_answer: str) -> str:
    """Grades the learner's answer to the practice question stashed in
    `pending` (session.data["pending_practice"] — see app.worker), updates
    learner_topic_mastery, logs the attempt, and returns the feedback
    message. This is the write side of the mastery loop that was missing
    (see tutobuddy-pedagogy-mastery-pace-step.md's "known gaps")."""
    result = await llm.grade_practice_answer(
        pending["question"], pending.get("model_answer"), learner_answer, pending["grade"]
    )
    await record_practice_attempt(
        learner_id,
        pending["topic_id"],
        pending["question"],
        pending.get("model_answer"),
        learner_answer,
        result["correctness"],
    )
    return prompts.practice_feedback_message(result["correctness"], result["feedback"])
