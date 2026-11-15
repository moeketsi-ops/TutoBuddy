"""Full learner journey on the real WhatsApp path: does every part of
Katlego actually run, in order, the way a learner would meet it?

    docker compose run --rm -e GATEWAY_URL=http://gateway:8000 -e MOCKWA_URL=http://mockwa:8001 \\
        evals python -m evals.journey.full

Steps (each is PASS, FAIL or WARN; WARN = the code ran but a model-dependent
expectation wasn't met, worth reading in the transcript):

  1  consent gate (no tutoring before AGREE), profile, grade
  2  the 15-minute check-in: every Grade 8 topic, pause on a real question,
     resume, report, baseline stored, topic mastery seeded
  3  tutoring with memory: the working problem survives follow-ups
  4  next day: new session, digest persisted, a review comes due
  5  practice ("quiz me") and its marking, PROGRESS, REPORT
  6  test prep: the learner names a test, PREP
  7  a sibling (ADD LEARNER, Grade 10): past paper marked against the memo,
     HELP and NEXT, report; SWITCH back
  8  study squad: NEW, results
  9  end-line check-in (CHECK-IN again): a second result stored
 10  usage: tokens and cost recorded per learner

Writes evals/bench/results/journey/journey-<time>.md with every step, the full
transcripts and the usage report for the two learners. Costs a few cents
with a real model (LLM_PROVIDER in .env); free on the stub.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
from pathlib import Path

from evals.journey.driver import Phone, learner_id, preflight, snapshot, time_travel, working_memory

# under evals/bench/results: that folder is mounted from your machine, so reports survive the container
OUT = Path(__file__).resolve().parents[1] / "bench" / "results" / "journey"
BANK = Path(__file__).resolve().parents[2] / "seed" / "diagnostic"


class Steps:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "", warn: bool = False) -> bool:
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        self.rows.append((status, name, detail))
        print(f"  {status:4}  {name}" + (f"  ({detail})" if detail and not ok else ""))
        return ok

    def table(self) -> str:
        lines = ["| | Step | Detail |", "|---|---|---|"]
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}
        for s, n, d in self.rows:
            lines.append(f"| {icon[s]} | {n} | {d.replace('|', '/')[:160]} |")
        return "\n".join(lines)


def _bank(grade):
    items = json.loads((BANK / f"grade_{grade:02d}.json").read_text())["items"]
    return {(i["topic"], i["kind"]): i for i in items}


def answer_checkin(phone: Phone, reply: str, grade: int, pick, *, stop_after: int | None = None) -> tuple[str, int]:
    """Answer check-in questions with pick(item) until done (or stop_after
    questions). Returns (last reply, questions answered)."""
    bank, n = _bank(grade), 0
    while "Check-in done" not in reply:
        head = next((l for l in reply.splitlines() if l.startswith("*Check-in")), None)
        if head is None or (stop_after is not None and n >= stop_after):
            break
        topic = head.split("·", 1)[1].strip(" *").replace(" (one more on this)", "")
        kind = "easier" if "one more on this" in head else "core"
        reply = phone.say(pick(bank[(topic, kind)]))
        n += 1
    return reply, n


GUARDIAN_AGREES = "AGREE Nomsa Dlamini, mother"  # consent needs the guardian's name


async def run() -> Path:
    from app.db import get_pool

    steps = Steps()
    if not await preflight():
        raise SystemExit(1)
    pool = await get_pool()
    a = Phone()
    print(f"Learner phone {a.number}")

    # 1. consent, profile, grade
    r = a.say("hi")
    steps.check("consent message first", "POPIA" in r and "AGREE" in r)
    r = a.say("How do I find the area of a rectangle?")
    steps.check("no tutoring before a guardian agrees", "AGREE" in r)
    steps.check("a bare AGREE asks for the guardian's name", "full name" in a.say("AGREE"))
    steps.check("AGREE with a name then name prompt", "call you" in a.say(GUARDIAN_AGREES).lower())
    steps.check("name then grade prompt", "grade" in a.say("Naledi").lower())
    welcome = a.say("8")
    steps.check("welcome and check-in start straight after the grade",
                "Grade 8" in welcome and "Check-in 1/22" in welcome, welcome[:120])

    # 2. check-in: weak on Area and Perimeter and Integers, else right
    def persona(it):
        if it["topic"] in ("Area and Perimeter", "Integers"):
            return next((l for l in "ABCD" if l != it["answer"]), "?")
        return it["answer"]
    r, n = answer_checkin(a, welcome, 8, persona, stop_after=5)
    r = a.say("How do I simplify 2x + 3x?")
    steps.check("a real question pauses the check-in", "Check-in paused" in r, r[-80:])
    r = a.say("CHECK-IN")
    steps.check("CHECK-IN resumes where it paused", "Carrying on" in r)
    r, n2 = answer_checkin(a, r, 8, persona)
    steps.check("check-in finishes with a report", "Check-in done, Naledi" in r, f"{n + n2} questions")
    steps.check("report names the weak topics as the plan", "Area and Perimeter" in r and "Integers" in r)
    async with pool.acquire() as conn:
        lid = await learner_id(conn, a, "Naledi")
        base = await conn.fetchrow("SELECT score_pct, topics FROM diagnostic_results WHERE learner_id = $1 "
                                   "ORDER BY finished_at LIMIT 1", lid)
        snap = await snapshot(conn, lid, ["Area and Perimeter", "Integers", "Exponents"])
    steps.check("baseline stored in diagnostic_results", base is not None,
                f"{base['score_pct']}%" if base else "")
    steps.check("topic mastery seeded from the check-in",
                snap["topics"].get("Area and Perimeter") == 20.0 and snap["topics"].get("Exponents") == 80.0,
                json.dumps({k: snap["topics"].get(k) for k in ("Area and Perimeter", "Exponents")}))

    # 3. tutoring with memory
    problem = "How do I find the area of a rectangle that is 7 cm by 4 cm?"
    r = a.say(problem)
    steps.check("tutoring reply asks the learner something", "?" in r, r[:100])
    a.say("11")
    mem = await working_memory(lid)
    steps.check("working problem kept after a wrong attempt",
                bool(mem) and (mem["working"]["problem"] or "").startswith("How do I find the area"),
                (mem or {}).get("working", {}).get("problem") or "none")
    a.say("28 square cm")
    mem = await working_memory(lid)
    steps.check("memory window records the turns", bool(mem) and len(mem["turns"]) >= 3,
                f"{len((mem or {}).get('turns', []))} turns")
    async with pool.acquire() as conn:
        ev = await conn.fetchval("SELECT count(*) FROM learner_events WHERE learner_id = $1 AND source = 'chat'", lid)
    steps.check("chat evidence written to mastery", ev >= 1, f"{ev} events", warn=True)

    # 4. next day
    async with pool.acquire() as conn:
        await time_travel(conn, lid, 1)
    async with pool.acquire() as conn:
        due = await conn.fetchval("SELECT count(*) FROM learner_lo_mastery WHERE learner_id = $1 "
                                  "AND next_review_at < now()", lid)
    steps.check("next day: a review has come due", due >= 1, f"{due} objectives due", warn=True)
    a.say("hi")
    q2 = "What is the perimeter of a square with sides of 5 cm?"
    r = a.say(q2)
    async with pool.acquire() as conn:
        digest = await conn.fetchval("SELECT memory_digest FROM learners WHERE id = $1", lid)
        strat = await conn.fetchval("SELECT strategy FROM llm_calls WHERE learner_id = $1 AND call = 'socratic_reply' "
                                    "ORDER BY id DESC LIMIT 1", lid)
    mem = await working_memory(lid)
    steps.check("next day: yesterday rolled into a stored digest", bool(digest and json.loads(digest)),
                (json.loads(digest) or [""])[-1][:100] if digest else "none")
    steps.check("next day: a new session on today's problem",
                bool(mem) and mem["working"]["problem"] == q2 and mem["session_turns"] == 1,
                f"session turns {(mem or {}).get('session_turns')}")
    steps.check("first question of the day opens with the due review (RETRIEVAL_PRACTICE)",
                strat == "RETRIEVAL_PRACTICE", f"strategy {strat}", warn=True)
    a.say("20")

    # 5. practice, PROGRESS, REPORT
    r = a.say("quiz me")
    steps.check("quiz me sets a practice question", "?" in r or "Grade 8" in r, r[:100])
    r = a.say("12")
    steps.check("practice answer is marked", bool(r.strip()), r[:100])
    steps.check("PROGRESS shows term mastery", "%" in a.say("PROGRESS"))
    steps.check("REPORT shows the check-in summary", "Check-in done" in a.say("REPORT"))

    # 6. test prep
    r = a.say("I'm writing a test on Friday on area and perimeter")
    steps.check("a test the learner mentions is noted with a plan", "Noted: test" in r and "Area and Perimeter" in r,
                r[:120])
    r = a.say("PREP")
    steps.check("PREP answers (Grade 8 has no papers yet, so it says so)", bool(r.strip()), r[:120])

    # 7. sibling on Grade 10: papers
    steps.check("ADD LEARNER asks a guardian to agree for the sibling", "AGREE" in a.say("ADD LEARNER"))
    steps.check("AGREE then name prompt", "call you" in a.say(GUARDIAN_AGREES).lower())
    a.say("Kabelo")
    r = a.say("10")
    steps.check("sibling gets their own Grade 10 check-in", "Check-in 1/13" in r)
    steps.check("PAUSE parks the check-in", "paused" in a.say("PAUSE").lower())
    r = a.say("PAPER")
    steps.check("PAPER lists Grade 10 papers", "Grade 10 past papers" in r)
    r = a.say("1")
    steps.check("a paper starts with question 1.1.1", "Question 1.1.1" in r, r[:100])
    r = a.say("6x^3 - 16x^2 + 11x - 2")
    steps.check("an answer is marked against the memo", bool(re.search(r"\d/2", r)), r[:120])
    r = a.say("HELP")
    steps.check("HELP works the question through (not counted)", "won't count" in r, r[:100])
    r = a.say("NEXT")
    steps.check("NEXT returns to the paper", "Question" in r)
    r = a.say("STOP")
    steps.check("STOP gives the paper report", "Marks:" in r or "done" in r, r[:120])
    async with pool.acquire() as conn:
        kid = await learner_id(conn, a, "Kabelo")
        pa = await conn.fetchval("SELECT count(*) FROM paper_attempts WHERE learner_id = $1", kid)
    steps.check("paper attempt stored", pa >= 1)

    # 8. squad
    r = a.say("SQUAD NEW")
    steps.check("SQUAD NEW gives a join code", bool(re.search(r"SQUAD JOIN \w{6}", r)))
    steps.check("SQUAD RESULTS shows the board", "Squad" in a.say("SQUAD RESULTS"))
    r = a.say("SWITCH")
    r = a.say("Naledi")
    steps.check("SWITCH back to the first learner", "Naledi" in r)

    # 9. end-line check-in
    r = a.say("CHECK-IN")
    r, _ = answer_checkin(a, r, 8, lambda it: it["answer"])
    async with pool.acquire() as conn:
        n_results = await conn.fetchval("SELECT count(*) FROM diagnostic_results WHERE learner_id = $1", lid)
    steps.check("end-line check-in stored (second result)", n_results == 2, f"{n_results} results")

    # 10. usage
    from app.reports import usage

    async with pool.acquire() as conn:
        data = await usage.collect(conn, datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3))
        data["calls"] = [c for c in data["calls"] if c["learner_id"] in (lid, kid)]
        data["msgs"] = [m for m in data["msgs"] if m["learner_id"] in (lid, kid)]
        calls = len(data["calls"])
    steps.check("model calls recorded against each learner", calls >= 1, f"{calls} calls")
    use = usage.report(data, usage.per_learner(data), 3, None)
    errs = a.errors
    steps.check("no 'something went wrong' replies", errs == 0,
                f"{errs} error replies; see `docker compose logs worker --tail 80`")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"journey-{datetime.datetime.now():%Y%m%d-%H%M}.md"
    fails = sum(1 for s, _, _ in steps.rows if s == "FAIL")
    warns = sum(1 for s, _, _ in steps.rows if s == "WARN")
    path.write_text(
        f"# Full learner journey, {datetime.datetime.now():%d %b %Y %H:%M}\n\n"
        f"{len(steps.rows)} steps: {len(steps.rows) - fails - warns} pass, {warns} warn, {fails} fail.\n\n"
        f"{steps.table()}\n\n{use}\n\n## Transcript\n\n```\n{a.transcript()}\n```\n")
    print(f"\n{len(steps.rows) - fails - warns} pass, {warns} warn, {fails} fail. Report: {path}")
    return path


if __name__ == "__main__":
    asyncio.run(run())
