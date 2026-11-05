"""WhatsApp flow for real past papers, test prep and study squads (the
worker calls `handle` before its own routing; None means "not mine").

Commands:
  PAPER                 list this grade's papers; reply a number to start
  PAPER <topic>         past-paper questions on one topic
  PREP                  questions for the learner's coming test (what they
                        told Katlego), else what the ATP suggests now
  SQUAD / SQUAD NEW / SQUAD JOIN <code> / SQUAD PAPER / SQUAD START /
  SQUAD RESULTS / SQUAD LEAVE
In a paper: an answer is marked against the memo; HELP works the question
through step by step with the tutor (not counted); NEXT goes on after
help; SKIP; STOP ends with the report.
A message about a coming test ("test on Friday on functions") is noted.
"""

from __future__ import annotations

import datetime

from app.db import get_pool
from app.orchestrator import session
from app.tutor import papers, test_prep

ADMIN = {"RESET", "DELETE", "SWITCH", "ADD LEARNER", "PROGRESS", "REPORT", "CHECK-IN", "CHECKIN",
         "CHECK IN", "PAUSE"}
PAPER_FOOTER = "\n\n_(Paper paused while we work on this · NEXT = next question · STOP = end)_"


def _today() -> datetime.date:
    return datetime.date.today()


async def _grade_topics(conn, grade: int) -> list[str]:
    rows = await conn.fetch(
        "SELECT t.name FROM topics t JOIN grades g ON g.id = t.grade_id WHERE g.grade_number = $1",
        grade)
    return [r["name"] for r in rows]


async def _finish(sess, state) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await papers.save_attempt(conn, sess.active_learner_id, state)
    sess.data.pop("paper", None)
    await session.save(sess)
    return papers.summary(state, sess.name)


async def _next_or_finish(sess, state, prefix: str = "") -> str:
    if papers.finished(state):
        return prefix + await _finish(sess, state)
    await session.save(sess)
    return prefix + papers.current_text(state)


async def _start_items(sess, items, label, *, paper_id=None, squad=None) -> str:
    if not items:
        return "I don't have past-paper questions on that yet. Say \"quiz me\" for practice questions."
    state = papers.start(paper_id, sess.active_learner_id, items=items, squad=squad, label=label)
    sess.data["paper"] = state
    sess.data.pop("paper_menu", None)
    await session.save(sess)
    intro = (f"📝 *{label}*: {len(items)} question{'s' if len(items) > 1 else ''}. "
             "I'll mark each answer against the official memo.\n\n")
    return intro + papers.current_text(state)


async def handle(sess, text: str, tutor_reply) -> tuple[str, str] | None:
    command = " ".join(text.strip().upper().split())
    if command in ADMIN:
        return None  # the worker's own commands always win
    state = sess.data.get("paper")
    if state and state.get("learner_id") != sess.active_learner_id:
        sess.data.pop("paper", None)  # a sibling's paper
        state = None

    # ── inside a paper ──
    if state:
        if command == "STOP":
            return await _finish(sess, state), "paper"
        if state.get("help"):
            if command in ("NEXT", "BACK", "CONTINUE"):
                papers.record(state, None, helped=True)
                return await _next_or_finish(sess, state, "Back to the paper 📝\n\n"), "paper"
            reply = await tutor_reply(text, sess.grade, sess.active_learner_id, sess.name)
            await session.save(sess)
            return reply + PAPER_FOOTER, "paper_help"
        if command == "SKIP":
            papers.record(state, None, skipped=True)
            return await _next_or_finish(sess, state, "Skipped 👍\n\n"), "paper"
        if command == "HELP":
            p, q = papers.current(state)
            state["help"] = True
            await session.save(sess)
            problem = (f"{q['context']} " if q.get("context") else "") + q["text"]
            reply = await tutor_reply(problem, sess.grade, sess.active_learner_id, sess.name,
                                      reference=q["answer"])
            return ("Let's work through it together (this one won't count towards your marks) 🤝\n\n"
                    + reply + PAPER_FOOTER), "paper_help"
        if command in ("PAPER", "PREP") or command.startswith(("SQUAD", "PAPER ")):
            return ("You're in the middle of a paper. Send STOP to end it first (you'll get your "
                    "report), then try again."), "paper"
        p, q = papers.current(state)
        res = await papers.mark(q, text, sess.grade)
        papers.record(state, res)
        tick = "✅" if res["awarded"] == res["of"] else ("🟡" if res["awarded"] else "❌")
        fb = f"{tick} *{res['awarded']}/{res['of']}* · {res['feedback']}"
        if res["awarded"] < res["of"]:
            fb += "\n" + papers.memo_text(q)
        return await _next_or_finish(sess, state, fb + "\n\n"), "paper"

    # ── choosing from the PAPER list ──
    menu = sess.data.get("paper_menu")
    if menu and command.isdigit():
        papers_ = papers.for_grade(sess.grade)
        i = int(command) - 1
        if 0 <= i < len(papers_):
            p = papers_[i]
            sq = menu.get("squad")
            if sq:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute("UPDATE squads SET paper_id = $2 WHERE code = $1", sq, p["id"])
                sess.data.pop("paper_menu", None)
                await session.save(sess)
                return (f"Squad paper set: *{p['title']}* 👥 Tell your squad to send SQUAD START. "
                        "Send SQUAD START yourself to begin."), "squad"
            items = [(p["id"], k) for k in range(len(p["questions"]))]
            return await _start_items(sess, items, p["title"], paper_id=p["id"]), "paper"

    # ── PAPER / PAPER <topic> ──
    if command == "PAPER":
        sess.data["paper_menu"] = {"squad": None}
        await session.save(sess)
        return papers.menu(sess.grade), "paper"
    if command.startswith("PAPER "):
        pool = await get_pool()
        async with pool.acquire() as conn:
            topics = test_prep.topics_named(text[6:], await _grade_topics(conn, sess.grade))
        items = papers.questions_on(sess.grade, topics)
        label = f"Past-paper questions: {', '.join(topics)}" if topics else "Past-paper questions"
        return await _start_items(sess, items, label), "paper"

    # ── PREP ──
    if command == "PREP":
        pool = await get_pool()
        async with pool.acquire() as conn:
            test = await test_prep.upcoming(conn, sess.active_learner_id, _today())
            if test and test["topics"]:
                items = papers.questions_on(sess.grade, test["topics"])
                label = f"Test prep: {', '.join(test['topics'])}"
                if items:
                    return await _start_items(sess, items, label), "prep"
            atp = test_prep.atp_suggestion(await test_prep.atp_rows(conn, sess.grade), _today())
        if atp and atp["kind"] == "topic":
            items = papers.questions_on(sess.grade, atp["topics"])
            note = (f"By the ATP (Term {atp['term']}, week {atp['week']}), your class has probably "
                    f"just finished {', '.join(atp['topics'])}, so a test is likely. School dates "
                    "vary: tell me your real test date and topics any time.\n\n")
            if items:
                return note + await _start_items(sess, items, f"Test prep: {', '.join(atp['topics'])}"), "prep"
            return note + "I don't have past-paper questions on that yet. Say \"quiz me\" for practice.", "prep"
        if atp and atp["kind"] in ("exam", "revision"):
            sess.data["paper_menu"] = {"squad": None}
            await session.save(sess)
            return (f"By the ATP (Term {atp['term']}, week {atp['week']}) it's "
                    f"{'exam' if atp['kind'] == 'exam' else 'revision'} time 📚 A full paper is the "
                    "best practice.\n\n" + papers.menu(sess.grade)), "prep"
        sess.data["paper_menu"] = {"squad": None}
        await session.save(sess)
        return ("Tell me about your next test (\"test on Friday on functions\") and I'll aim the "
                "practice at it. Or pick a paper:\n\n" + papers.menu(sess.grade)), "prep"

    # ── SQUAD ──
    if command.startswith("SQUAD"):
        return await _squad(sess, command), "squad"

    # ── a coming test, in the learner's own words ──
    if test_prep.mentions_test(text):
        pool = await get_pool()
        async with pool.acquire() as conn:
            topics = test_prep.topics_named(text, await _grade_topics(conn, sess.grade))
            due = test_prep.due_date(text, _today())
            await test_prep.save(conn, sess.active_learner_id, due, topics, text)
        if not topics:
            sess.data["awaiting_test_topics"] = True
            await session.save(sess)
            return ("Good to know 📅 Which topics will the test cover? (e.g. functions, "
                    "trig, number patterns)"), "test"
        return test_prep.plan_text(due, topics, _today(),
                                   papers.topics_with_questions(sess.grade)), "test"
    if sess.data.pop("awaiting_test_topics", None):
        pool = await get_pool()
        async with pool.acquire() as conn:
            topics = test_prep.topics_named(text, await _grade_topics(conn, sess.grade))
            if topics:
                await conn.execute(
                    "UPDATE learner_tests SET topics = $2::jsonb WHERE id = (SELECT id FROM "
                    "learner_tests WHERE learner_id = $1 ORDER BY created_at DESC LIMIT 1)",
                    sess.active_learner_id, __import__("json").dumps(topics))
                test = await test_prep.upcoming(conn, sess.active_learner_id, _today())
        await session.save(sess)
        if topics:
            return test_prep.plan_text(test and test["due"], topics, _today(),
                                       papers.topics_with_questions(sess.grade)), "test"
        # not topics after all: carry on as a normal message
    return None


async def _squad(sess, command: str) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        mine = await papers.squad_of(conn, sess.active_learner_id)
        if command in ("SQUAD NEW", "SQUAD CREATE"):
            code = await papers.create_squad(conn, sess.active_learner_id, sess.grade)
            return (f"Squad *{code}* created 👥 Friends in Grade {sess.grade} join with:\n"
                    f"SQUAD JOIN {code}\n\nSquad members see each other's nicknames and paper "
                    "marks, nothing else. Send SQUAD PAPER to choose the squad's paper.")
        if command.startswith("SQUAD JOIN"):
            code = command.replace("SQUAD JOIN", "").strip()
            if not code:
                return "Send SQUAD JOIN and the code your friend shared, e.g. SQUAD JOIN K7M2QX."
            err = await papers.join_squad(conn, sess.active_learner_id, sess.grade, code)
            if err:
                return err
            sq = await papers.squad_of(conn, sess.active_learner_id)
            return (f"You're in squad *{sq['code']}* 👥 Your nickname and paper marks are shared "
                    "with the squad. Send SQUAD START to do the squad's paper"
                    + ("" if sq["paper_id"] else " once one is chosen (SQUAD PAPER)") + ".")
        if not mine:
            return ("Study squads: do the same past paper as your friends and compare marks 👥\n"
                    "• SQUAD NEW to start one\n• SQUAD JOIN <code> to join a friend's")
        if command == "SQUAD LEAVE":
            await conn.execute("DELETE FROM squad_members WHERE learner_id = $1", sess.active_learner_id)
            return f"You've left squad {mine['code']}."
        if command == "SQUAD PAPER":
            sess.data["paper_menu"] = {"squad": mine["code"]}
            await session.save(sess)
            return "Pick the squad's paper:\n\n" + papers.menu(sess.grade)
        if command == "SQUAD RESULTS":
            return await papers.squad_results(conn, mine["code"], mine["paper_id"])
        if command == "SQUAD START":
            if not mine["paper_id"] or not papers.get(mine["paper_id"]):
                return "Your squad hasn't chosen a paper yet. Send SQUAD PAPER to pick one."
            p = papers.get(mine["paper_id"])
    if command == "SQUAD START":
        items = [(p["id"], k) for k in range(len(p["questions"]))]
        return await _start_items(sess, items, p["title"], paper_id=p["id"], squad=mine["code"])
    paper = papers.get(mine["paper_id"]) if mine["paper_id"] else None
    return (f"You're in squad *{mine['code']}*"
            + (f", doing {paper['title']}" if paper else "")
            + ".\n• SQUAD START to do the squad paper\n• SQUAD RESULTS for the scoreboard\n"
            "• SQUAD PAPER to choose the paper\n• SQUAD LEAVE")
