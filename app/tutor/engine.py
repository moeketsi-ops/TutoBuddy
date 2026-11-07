"""Tutor engine: retrieve grounded context, then reply Socratically —
plus term-progress reporting and practice-question generation, both grounded
in learner_topic_mastery / topics (see app.tutor.rag)."""

import datetime
import logging
import random
import re

from app.adapters import ledger, llm
from app.config import settings
from app.db import get_pool
from app.tutor import answer_check, mastery, memory, pedagogy, prompts, representation, tmu
from app.tutor.state import parse_state, parse_turn, strip_state
from app.tutor.rag import (
    get_past_paper_excerpts,
    get_term_progress,
    grade_scoped_context,
    term_focus_for,
    topic_chunks,
    topic_hint,
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
                      name: str | None = None, *, reference: str | None = None) -> str:
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

    `reference`: the memo answer when the problem is a past-paper question
    the learner asked to work through (HELP in a paper). It guides the
    model and the leak guard, and stays with the working problem.

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
    memory.ensure_working(mem)
    continuing = memory.continues_problem(mem, question)
    # Code judges what it can before the call (CPA spec section 5), so the
    # model is told, not asked, whether "x = 10" is right.
    check = answer_check.check(mem["working"]["problem"], question) if continuing else None

    # A reply like "x = 6" retrieves nothing useful on its own; search with
    # the working problem attached so the notes stay on topic.
    query = f"{mem['working']['problem']} {question}" if continuing else question
    # Mid-problem the notes were already shown on the opening turn: two are
    # enough to stay grounded (~120 fewer prompt tokens a turn).
    ctx = await grade_scoped_context(query, grade, k=2 if continuing else 3)
    hint = None
    if not continuing and not ctx["above"]:
        hint = topic_hint(question, ctx["grade_topics"])
        if hint and hint not in [c["topic"] for c in ctx["chunks"]]:
            first = await topic_chunks(grade, hint)
            seen = {c["content"] for c in first}
            ctx["chunks"] = (first + [c for c in ctx["chunks"] if c["content"] not in seen])[:3]
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
                    conn, grade, ([hint] if hint else []) + [c["topic"] for c in ctx["chunks"]],
                    mem["working"]["topic_id"])
        los = await mastery.lo_candidates(
            conn, topic["id"], query=query, keep_code=mem["working"]["lo_code"]) if topic else []
        miscs = await mastery.misconception_codes(conn, topic["id"] if topic else None)
        stats = await pedagogy.load_stats(conn, learner_id, topic["id"]) if topic else {}
        level_stats = await representation.load_stats(conn, learner_id, topic["id"]) if topic else {}
        # The objective in play: the working one when continuing, else the
        # best match for this question.
        focus = (next((lo for lo in los if lo["code"] == mem["working"]["lo_code"]), None)
                 if continuing else None) or (los[0] if los else None)
        lo_score = await conn.fetchval(
            "SELECT mastery_score FROM learner_lo_mastery WHERE learner_id = $1 AND lo_id = $2",
            learner_id, focus["id"]) if focus else None
        lo_score = float(lo_score) if lo_score is not None else None
        topic_score = None
        if lo_score is None and topic:
            # No evidence on this objective yet: pitch from the topic score
            # (the sign-up check-in seeds it), not the neutral 50.
            topic_score = await conn.fetchval(
                "SELECT mastery_score FROM learner_topic_mastery WHERE learner_id = $1 AND topic_id = $2",
                learner_id, topic["id"])
            topic_score = float(topic_score) if topic_score is not None else None
        layered = settings.prompt_layout.strip().lower() == "layered"
        profile_lines = (await _profile_lines(conn, learner_id)
                         if layered and not mem.get("profile") else [])
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
    score = lo_score if lo_score is not None else (
        topic_score if topic_score is not None else mastery.MASTERY_START)
    rng = random.Random(f"{learner_id}:{mem['session_turns']}")
    # choose() keeps its guard-rail rules (review, new objective, repeated
    # misconception, hint and reveal); the 3-turn switch is plan_switch's.
    base = pedagogy.choose(**dict(
        score=score,
        current=w["strategy"],
        fails_in_row=0,
        tried_on_problem=[] if new_problem else w["tried"],
        new_lo_this_session=bool(lo_code) and lo_code not in mem["los_seen"] and lo_score is None,
        misconception_repeated=len(w["misc_recent"]) != len(set(w["misc_recent"])),
        review_due=review is not None,
        has_open_problem=continuing,
        asked_answer_count=(0 if new_problem else w["asked_answer"])
                           + int(memory.asks_for_answer(question)),
        wrong_on_problem=0 if new_problem else w["wrong_on_problem"],
        stats=stats,
        rng=rng,
    ))
    if continuing and w.get("level"):
        level, level_why = w["level"], "same level"
    else:
        level, level_why = representation.start_level(score, level_stats)
    verdict = check["verdict"] if check else None
    decision = pedagogy.plan_switch(
        base, current_strategy=w["strategy"] if continuing else None, level=level,
        no_progress=0 if new_problem else w["no_progress"],
        switches_used=0 if new_problem else w["switches"],
        asked_other_way=continuing and memory.asks_other_way(question),
        tried=[] if new_problem else w["tried"], stats=stats, rng=rng, code_verdict=verdict)
    if new_problem:
        decision["level_why"] = level_why
    if decision.get("close") and decision["level"] != "abstract" and not w.get("bridge"):
        # Solved with objects or a picture: ask for the symbols before closing.
        decision.pop("close")
        decision["bridge"] = True
        decision["code_check"] = ("CODE CHECK: the learner's latest message is a CORRECT answer to "
                                  "the working problem. Praise what they did, specifically.")
    else:
        decision["code_check"] = answer_check.prompt_line(check)
    ref = reference if not continuing else w.get("reference")
    if ref:
        decision["code_check"] = "\n".join(filter(None, [
            decision.get("code_check"),
            f"MEMO ANSWER for this past-paper question (guide towards it; never state it before the "
            f"learner reaches it): {ref}"]))
    decision["mid_chat"] = mem["session_turns"] > 0
    if (decision["strategy"] == "MULTIPLE_METHODS" or decision.get("fallback") == "MULTIPLE_METHODS"
            or decision.get("switch") in ("strategy", "worked_example") or new_problem):
        entry = tmu.find_methods(w["problem"] if continuing else question, grade,
                                 (topic or {}).get("name"))
        decision["methods"] = tmu.methods_line(entry)
        decision["methods_id"] = entry["id"] if entry else None
    ledger.current_strategy.set(decision["strategy"])

    # Mid-problem, the objective in play is known: list only that one.
    prompt_los = [focus] if (continuing and focus and focus["code"] == w["lo_code"]) else los
    call = dict(
        question=question, chunks=ctx["chunks"], grade=grade, above=ctx["above"],
        # Topic list only when it's needed to judge an off-grade question
        # (saves ~200 prompt tokens on most turns).
        grade_topics=ctx["grade_topics"] if (ctx["above"] or not ctx["chunks"]) else None,
        term_focus=term_focus,
        memory_block=None if layered else memory.prompt_block(mem, name=name, grade=grade,
                                                              lo_score=lo_score, review=review),
        pedagogy=decision, lo_candidates=prompt_los, misconceptions=miscs, continuing=continuing,
    )
    if layered:
        # Cache-friendly layout: the grade's topic list always goes in the
        # (cached) grade frame; profile frozen for the session; turns as chat.
        call["grade_topics"] = ctx["grade_topics"]
        call["layered"] = {
            "profile": memory.profile_block(mem, name=name, grade=grade, lines=profile_lines),
            "turn_memory": memory.turn_block(mem, lo_score=lo_score, review=review),
            "history": memory.history_messages(mem),
        }
    # Leak guard: code knows the answer to many problems. Unless the engine
    # allowed a reveal, or the learner has already reached the answer, a
    # reply that states it is written again once, then masked.
    forms = [] if (decision.get("reveal") or (check or {}).get("verdict") == "correct"
                   or (continuing and w.get("answered"))) \
        else (answer_check.answer_forms(w["problem"] if continuing else question)
              or (answer_check.forms_from_answer(ref, question) if ref else []))
    reply, body, parsed_as, guard = await _reply_with_guard(call, forms, mid_chat=decision["mid_chat"])
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

    if check:
        ev_code, progress_code = answer_check.EVIDENCE[check["verdict"]]
        if state is None:
            state = {"lo": None, "misc": None, "strategy": decision["strategy"],
                     "hint": decision["hint"], "step": None, "level": None, "valid": False}
        state = {**state, "ev": ev_code, "progress": progress_code, "code_checked": True}
    # A pending fallback the model was told to apply if this message made no
    # progress: code can now see whether it did.
    no_progress_now = bool(state) and state.get("ev") in ("attempt_wrong", "attempt_partial",
                                                          "asked_for_answer") \
        and state.get("progress") not in ("step_forward", "solved")
    if not decision.get("switch") and no_progress_now and (decision.get("fallback")
                                                            or decision.get("fallback_level")):
        decision["switch"] = "level" if decision.get("fallback_level") else (
            "worked_example" if decision["fallback"] == "WORKED_EXAMPLE" else "strategy")
        decision["trigger"] = "no_progress"
        decision["switches_used"] = decision.get("switches_used", 0) + 1
        if decision.get("fallback_level"):
            decision["level"] = decision["fallback_level"]
        else:
            decision["strategy"] = decision["fallback"]
        decision["applied_fallback"] = True

    used = (state or {}).get("strategy") or decision["strategy"]
    if decision.get("applied_fallback") and decision.get("fallback"):
        used = decision["strategy"]
    ev = (state or {}).get("ev", "none")
    progress = (state or {}).get("progress")
    prev_level = w.get("level")
    level_shown = (state or {}).get("level") or prev_level
    # `ev` judges the learner's message, which answered the PREVIOUS reply:
    # credit that reply's strategy, hint level and topic, not this one's.
    prev_strategy, prev_hint, prev_topic = w["strategy"], w.get("last_hint", 0), w["topic_id"]
    ev_topic_id = prev_topic if (continuing and prev_topic) else (topic["id"] if topic else None)
    # Saying an answer already reached again ("thanks, area = 24 cm²") is not new
    # evidence: counting each restatement took mastery from 20 to 91 on day 1
    # of the AI-learner week (5 Nov) and inflated strategy success.
    restated = bool(continuing and w.get("answered") and ev in ("attempt_correct", "explained_back"))
    ev_result = None
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                if ev_topic_id and ev != "none" and not restated:
                    lo_id = next((lo["id"] for lo in los
                                  if lo["code"] == state.get("lo") and ev_topic_id == (topic or {}).get("id")),
                                 None)
                    ev_result = await mastery.record_event(
                        conn, learner_id, ev_topic_id, source="chat", evidence=ev,
                        lo_id=lo_id, hint_level=prev_hint, strategy=prev_strategy or used,
                        misconception=state.get("misc"), cpa_level=level_shown,
                        strand=tmu.strand_for(prev_strategy or used, ev, level_shown))
                ok = None if restated else pedagogy.outcome(ev)
                if prev_topic and prev_strategy and ok is not None:
                    await pedagogy.record_outcome(conn, learner_id, prev_topic, prev_strategy, ok)
                moved = progress in ("step_forward", "solved") or ok is True
                if prev_topic and prev_level and (ok is not None or progress):
                    await representation.record_outcome(conn, learner_id, prev_topic, prev_level, moved)
                # Evidence log: close the last switch's outcome, then log a new one.
                if w.get("last_switch_id"):
                    w["since_switch"] = w.get("since_switch", 0) + 1
                    if moved or w["since_switch"] >= 2:
                        await conn.execute(
                            "UPDATE pedagogy_decisions SET outcome = $2, turns_to_outcome = $3 "
                            "WHERE id = $1", w["last_switch_id"],
                            "progress" if moved else "no_progress", w["since_switch"])
                        w["last_switch_id"] = None
                if decision.get("switch"):
                    w["last_switch_id"] = await conn.fetchval(
                        """
                        INSERT INTO pedagogy_decisions
                            (learner_id, topic_id, problem, session_turn, trigger, switch, strategy,
                             cpa_level, chosen_by, mastery_at, no_progress)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id
                        """, learner_id, (topic or {}).get("id") or prev_topic, w.get("problem"),
                        mem["session_turns"], decision.get("trigger") or "no_progress",
                        decision["switch"], decision["strategy"], decision.get("level"),
                        decision.get("chosen_by", "engine"), score, w.get("no_progress", 0))
                    w["since_switch"] = 0
        except ValueError:
            log.warning("grade rule: evidence on topic %s refused", ev_topic_id)
        except Exception:  # noqa: BLE001 -- bookkeeping never costs the learner their reply
            log.exception("tutor_reply: evidence write failed (learner %s)", learner_id)

        mem_state = state
        if decision.get("bridge") and state:
            mem_state = {**state, "progress": "step_forward", "step": None}  # stay open for the bridge
        elif w.get("bridge") and continuing and state:
            mem_state = {**state, "progress": "solved"}  # bridge answered: close the problem
        switch_id, since = w.get("last_switch_id"), w.get("since_switch", 0)
        consolidate_now = memory.record_turn(mem, question, reply, mem_state, topic, used,
                                             new_problem=new_problem)
        w = mem["working"]
        if new_problem and w["problem"]:
            w["reference"] = reference
        if w["problem"] and ev in ("attempt_correct", "explained_back"):
            w["answered"] = True  # the learner has reached it: restating it is fine now
        if w["problem"]:
            w["level"] = decision.get("level")
            if continuing:  # a new problem doesn't inherit the old problem's open switch
                w["last_switch_id"], w["since_switch"] = switch_id, since
            if decision.get("switch"):
                w["no_progress"] = 0  # the new approach gets its own 3 turns
                w["switches"] = decision.get("switches_used", w.get("switches", 0))
            if decision.get("bridge"):
                w["bridge"] = True
        if consolidate_now:
            memory.consolidate(mem)
            mem["_persist"] = True
        if mem.pop("_persist", False):
            await memory.persist_digest(conn, mem)
    if decision.get("restart"):
        mem["working"].update(tried=[], fails_in_row=0, wrong_on_problem=0, no_progress=0)
    await memory.save(mem)
    last_turn.set({"decision": decision, "state": state, "topic": topic, "output_mode": mode,
                   "leak_guard": guard,
                   "continuing": continuing, "problem": mem["working"]["problem"],
                   "lo_score": lo_score, "level": decision.get("level"),
                   "switch": decision.get("switch"), "chosen_by": decision.get("chosen_by"),
                   "code_check": check["verdict"] if check else None,
                   "no_progress": mem["working"].get("no_progress"),
                   "switches": mem["working"].get("switches"),
                   "methods": decision.get("methods_id")})
    await _log_turn(learner_id, question, reply, decision, state, check, topic, ev_result, restated,
                    continuing, mem["working"], guard)
    return reply


async def _log_turn(learner_id, question, reply, decision, state, check, topic, ev_result, restated,
                    continuing, working, guard) -> None:
    """One row per tutoring turn in tutor_turns: what the engine decided and
    why, who judged the learner's message, and how mastery moved. It explains
    any learner's progress to a teacher or parent, and feeds the week
    walkthrough. Bookkeeping only: a failure never costs the learner a reply."""
    try:
        pool = await get_pool()
        st = state or {}
        judged = "code" if check else ("model" if st.get("ev") not in (None, "none") else "none")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tutor_turns (learner_id, topic_id, topic, lo_code, problem, new_problem,
                    learner_text, reply, judged_by, code_verdict, evidence, progress, misconception,
                    strategy, why, hint, reveal, level, switch, trigger, no_progress, switches,
                    mastery_before, mastery_after, topic_score, restated, leak_guard, layout)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                        $21,$22,$23,$24,$25,$26,$27,$28)
                """,
                learner_id, (topic or {}).get("id"), (topic or {}).get("name"), st.get("lo"),
                working.get("problem") or question[:200], not continuing, question[:500], reply[:2000],
                judged, check["verdict"] if check else None, st.get("ev"), st.get("progress"),
                st.get("misc"), decision.get("strategy"), str(decision.get("why") or "")[:200],
                decision.get("hint"), bool(decision.get("reveal")), decision.get("level"),
                decision.get("switch"), decision.get("trigger"), working.get("no_progress"),
                working.get("switches"),
                (ev_result or {}).get("before"), (ev_result or {}).get("after"),
                (ev_result or {}).get("topic_score"), restated, guard,
                settings.prompt_layout.strip().lower() or "classic")
    except Exception:  # noqa: BLE001
        log.exception("tutor_reply: turn log failed (learner %s)", learner_id)


LEAK_REDO = ("REWRITE: your draft stated the final answer ({answer}) before the learner reached "
             "it. Write the reply again without stating it, and without a calculation or count "
             "that ends at it. Stop one step short and ask the learner for that step.")


async def _reply_with_guard(call: dict, forms: list[str], *, mid_chat: bool):
    """(reply, state body, parsed_as, guard) for one tutoring turn. `guard`
    is None, "rewritten" (a second call fixed a leak) or "masked" (the
    second call leaked too, so code hid the answer)."""
    raw = await llm.socratic_reply(**call)
    reply, body, parsed_as = parse_turn(raw)
    if not reply.strip():
        # Unparseable JSON with no recoverable reply: never send raw output.
        raise RuntimeError("tutor_reply: model output had no usable reply")
    guard = None
    if forms and answer_check.gives_away(reply, forms):
        redo = {**call["pedagogy"],
                "code_check": "\n".join(filter(None, [call["pedagogy"].get("code_check"),
                                                      LEAK_REDO.format(answer=forms[0])]))}
        try:
            raw2 = await llm.socratic_reply(**{**call, "pedagogy": redo})
            reply2, body2, parsed2 = parse_turn(raw2)
        except Exception:  # noqa: BLE001 -- the first reply is still there to mask
            reply2 = ""
        if reply2.strip() and not answer_check.gives_away(reply2, forms):
            reply, body, parsed_as, guard = reply2, body2, parsed2, "rewritten"
        else:
            reply, guard = answer_check.mask(reply, forms), "masked"
        log.info("leak guard: %s", guard)
    if mid_chat:
        reply = strip_greeting(reply)
    return reply, body, parsed_as, guard


_GREETING = re.compile(
    r"^\s*(?i:hey|hi|hiya|hello|howzit|sawubona|dumela|molo)(?: there)?(?: [A-Z][\w'-]*)?"
    r"\s*[!,.]*\s*(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?\s*)*")


def strip_greeting(reply: str) -> str:
    """Mid-chat replies don't open with "Hey Bench! 👋" every turn. Only a
    greeting followed by more text is removed."""
    rest = _GREETING.sub("", reply, count=1)
    if rest is reply or len(rest.strip()) < 15:
        return reply
    rest = rest.lstrip()
    return rest[:1].upper() + rest[1:]


async def _profile_lines(conn, learner_id: int) -> list[str]:
    """The learner profile for the layered prompt: learning memory (weaker and
    stronger topics, the last check-in) and personalisation memory (what has
    worked for this learner). Read once per session."""
    lines = []
    topics = await conn.fetch(
        """
        SELECT t.name, m.mastery_score::float AS s FROM learner_topic_mastery m
        JOIN topics t ON t.id = m.topic_id WHERE m.learner_id = $1 ORDER BY m.mastery_score
        """, learner_id)
    if topics:
        weak = [f"{r['name']} {r['s']:.0f}%" for r in topics[:3] if r["s"] < 70]
        strong = [f"{r['name']} {r['s']:.0f}%" for r in topics[::-1][:2] if r["s"] >= 70]
        if weak:
            lines.append("WEAKER TOPICS " + "; ".join(weak))
        if strong:
            lines.append("STRONGER TOPICS " + "; ".join(strong))
    chk = await conn.fetchrow("SELECT score_pct, finished_at::date AS d FROM diagnostic_results "
                              "WHERE learner_id = $1 ORDER BY finished_at DESC LIMIT 1", learner_id)
    if chk:
        lines.append(f"CHECK-IN {float(chk['score_pct']):.0f}% on {chk['d']}")
    strat = await conn.fetch(
        """
        SELECT strategy, sum(tries) AS t, sum(successes) AS ok FROM learner_strategy_stats
        WHERE learner_id = $1 GROUP BY 1 HAVING sum(tries) >= 3
        ORDER BY sum(successes)::float / sum(tries) DESC, sum(tries) DESC LIMIT 2
        """, learner_id)
    if strat:
        lines.append("WORKS WELL " + "; ".join(
            f"{r['strategy'].lower().replace('_', ' ')} ({r['ok']}/{r['t']})" for r in strat))
    lvl = await conn.fetchrow(
        """
        SELECT cpa_level, sum(tries) AS t, sum(successes) AS ok FROM learner_level_stats
        WHERE learner_id = $1 GROUP BY 1 HAVING sum(tries) >= 3
        ORDER BY sum(successes)::float / sum(tries) DESC LIMIT 1
        """, learner_id)
    if lvl:
        lines.append(f"BEST LEVEL {lvl['cpa_level']} ({lvl['ok']}/{lvl['t']} moved forward)")
    return lines


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
