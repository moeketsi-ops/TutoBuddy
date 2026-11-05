"""Sign-up check-in: a multiple-choice diagnostic over every CAPS topic in
the learner's grade, run straight after onboarding.

Why: every learner used to start every topic at the same neutral mastery
(50), so Katlego's first lessons were pitched blind, parents had nothing to
see on day one and pilot partners had no baseline. The check-in sets a
starting score per topic, names the misconceptions behind wrong options,
picks the first topics to work on, and stores the result as the learner's
baseline (re-run later with CHECK-IN for an end-line).

How it runs (founder decisions, 5 Nov 2026):
- every topic of the grade, scored the same whatever the term (no ATP
  discount for untaught topics);
- one "core" item per topic; a miss (or "?") brings that topic's "easier"
  item next, so one slip doesn't mark a topic weak;
- a fixed, reviewed bank (seed/diagnostic/grade_XX.json), so baselines are
  comparable across learners. Grade 9 has no bank yet: no check-in.

Scores: core right 80, core missed but easier right 50, both missed 20.
These seed learner_topic_mastery only where the learner has no evidence on
that topic yet; later evidence moves each objective from there
(mastery.record_event starts a new objective at the topic score).
All state lives in the Redis session (sess.data["diagnostic"]); nothing
here calls a model.
"""

from __future__ import annotations

import datetime
import json
import re
from functools import lru_cache
from pathlib import Path

BANK_DIR = Path(__file__).resolve().parents[2] / "seed" / "diagnostic"
SCORES = {"core": 80.0, "easier": 50.0, "none": 20.0}
LETTERS = "ABCD"
DONT_KNOW = re.compile(r"^\s*(\?+|i\s*don'?t\s*know|idk|not\s*sure|no\s*idea|skip)\s*[.!]*\s*$",
                       re.IGNORECASE)
_LETTER = re.compile(r"^\s*(?:option\s+|answer\s+|it'?s\s+)?\(?([abcd])\)?\s*[.):]?\s*$", re.IGNORECASE)

MISC_WORDS = {
    "SIGN_ERR": "signs with negative numbers",
    "ONE_SIDE_OP": "doing the same thing to both sides of an equation",
    "UNLIKE_TERMS": "adding unlike terms",
    "PARTIAL_DISTRIB": "multiplying every term in brackets",
    "ORDER_OPS": "the order of operations",
    "EXP_AS_MULT": "what an exponent means",
    "FRAC_ADD_ACROSS": "adding fractions",
    "PLACE_VALUE": "place value and decimals",
    "UNITS": "units",
}


@lru_cache(maxsize=8)
def bank(grade: int) -> dict | None:
    path = BANK_DIR / f"grade_{grade:02d}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    data["by_id"] = {i["id"]: i for i in data["items"]}
    return data


def available(grade: int | None) -> bool:
    return bool(grade) and bank(grade) is not None


def start(grade: int) -> dict:
    """A fresh check-in state for the session."""
    b = bank(grade)
    core = [i["id"] for i in b["items"] if i["kind"] == "core"]
    return {"grade": grade, "version": b["version"], "queue": core, "i": 0, "answers": {},
            "paused": False, "topics": len(core),
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def current(state: dict) -> dict | None:
    if state["i"] >= len(state["queue"]):
        return None
    return bank(state["grade"])["by_id"][state["queue"][state["i"]]]


def question_text(state: dict) -> str:
    it = current(state)
    done_topics = sum(1 for q in state["queue"][:state["i"]]
                      if bank(state["grade"])["by_id"][q]["kind"] == "core")
    head = (f"Check-in {done_topics + 1}/{state['topics']} · {it['topic']}" if it["kind"] == "core"
            else f"Check-in · {it['topic']} (one more on this)")
    opts = "\n".join(f"{l}) {o}" for l, o in zip(LETTERS, it["options"]))
    return f"*{head}*\n\n{it['stem']}\n\n{opts}\n\nReply A, B, C or D. Not sure? Reply ?"


def intro(name: str, grade: int) -> str:
    n = bank(grade) and sum(1 for i in bank(grade)["items"] if i["kind"] == "core")
    return (f"Before we dive in, a quick check-in so I know where to start, {name} 📋 It covers all "
            f"{n} Grade {grade} topics, one question each (about 15 minutes). It isn't a test: "
            f"\"?\" is a fine answer.\n\nSend PAUSE to stop and CHECK-IN to carry on later.")


def parse_answer(text: str, item: dict) -> str | None:
    """'A'..'D', '?' for don't know, or None when the message isn't an
    answer (a question, a greeting): then the check-in pauses."""
    if DONT_KNOW.match(text):
        return "?"
    m = _LETTER.match(text)
    if m:
        return m.group(1).upper()
    norm = lambda s: re.sub(r"\s+", "", s.lower())  # noqa: E731
    for letter, opt in zip(LETTERS, item["options"]):
        if norm(text) == norm(opt):
            return letter
    return None


def answer(state: dict, letter: str) -> None:
    """Record the answer to the current item and move on. A missed core
    item queues that topic's easier item next."""
    it = current(state)
    state["answers"][it["id"]] = letter
    if it["kind"] == "core" and letter != it["answer"]:
        easier = next(i["id"] for i in bank(state["grade"])["items"]
                      if i["topic"] == it["topic"] and i["kind"] == "easier")
        state["queue"].insert(state["i"] + 1, easier)
    state["i"] += 1


def finished(state: dict) -> bool:
    return state["i"] >= len(state["queue"])


def results(state: dict) -> dict:
    """{topic: {"score", "level", "misc": [codes]}} plus totals."""
    b = bank(state["grade"])
    topics: dict[str, dict] = {}
    for it in b["items"]:
        if it["id"] not in state["answers"]:
            continue
        got = state["answers"][it["id"]]
        t = topics.setdefault(it["topic"], {"core": None, "easier": None, "misc": []})
        t[it["kind"]] = got == it["answer"]
        code = it["misc"].get(got)
        if code and code != "MISREAD":
            t["misc"].append(code)
    out = {}
    for topic, t in topics.items():
        level = "core" if t["core"] else ("easier" if t["easier"] else "none")
        out[topic] = {"score": SCORES[level], "level": level, "misc": t["misc"]}
    first_try = sum(1 for t in out.values() if t["level"] == "core")
    return {"topics": out, "first_try": first_try, "answered": len(out),
            "score_pct": round(100 * sum(t["score"] for t in out.values()) / (100 * len(out)), 1)
            if out else 0.0}


def focus(res: dict, weights: dict[str, float] | None = None, n: int = 3) -> list[str]:
    """The topics to start on: lowest score first; among equals, the topic
    with more CAPS teaching time (it carries more marks)."""
    weights = weights or {}
    weak = [t for t, r in res["topics"].items() if r["level"] != "core"]
    return sorted(weak, key=lambda t: (res["topics"][t]["score"], -weights.get(t, 0.0), t))[:n]


def report(name: str, grade: int, res: dict, focus_topics: list[str]) -> str:
    """The learner's (and parent's) first report, as one WhatsApp message."""
    tops = res["topics"]
    strong = [t for t, r in tops.items() if r["level"] == "core"]
    middle = [t for t, r in tops.items() if r["level"] == "easier"]
    lines = [f"Check-in done, {name}! 🎉 Here's where you are in Grade {grade} Maths:"]
    if strong:
        lines.append(f"\n💪 *Strong*: {', '.join(strong)}")
    if middle:
        lines.append(f"\n🌱 *Getting there*: {', '.join(middle)}")
    weak = [t for t, r in tops.items() if r["level"] == "none"]
    if weak:
        lines.append(f"\n🎯 *Needs work*: {', '.join(weak)}")
    miscs: dict[str, int] = {}
    for r in tops.values():
        for c in r["misc"]:
            miscs[c] = miscs.get(c, 0) + 1
    repeat = [MISC_WORDS[c] for c, k in sorted(miscs.items(), key=lambda kv: -kv[1])
              if k >= 2 and c in MISC_WORDS]
    if repeat:
        lines.append(f"\n🔎 A pattern to fix: {repeat[0]}.")
    if focus_topics:
        lines.append(f"\n*Your plan*: we start with {focus_topics[0]}"
                     + (f", then {', '.join(focus_topics[1:])}" if len(focus_topics) > 1 else "")
                     + ". Say \"quiz me\" or ask me anything on it.")
    else:
        lines.append("\n*Your plan*: you're strong across the board, so we'll stretch you with "
                     "harder, exam-style questions. Say \"quiz me\" to start.")
    lines.append("\nSend PROGRESS any time to see your levels, or REPORT for this summary.")
    return "\n".join(lines)


# ── Database side ────────────────────────────────────────────────────────────

async def save(conn, learner_id: int, state: dict, res: dict, focus_topics: list[str]) -> None:
    """Store the baseline, seed topic mastery where there is no evidence
    yet, and log one diagnostic event per topic (learner_events)."""
    grade = state["grade"]
    rows = await conn.fetch(
        "SELECT t.id, t.name FROM topics t JOIN grades g ON g.id = t.grade_id "
        "WHERE g.grade_number = $1", grade)
    ids = {r["name"]: r["id"] for r in rows}
    for topic, r in res["topics"].items():
        tid = ids.get(topic)
        if tid is None:
            continue
        has_evidence = await conn.fetchval(
            "SELECT count(*) FROM learner_lo_mastery m JOIN learning_objectives lo "
            "ON lo.id = m.lo_id WHERE m.learner_id = $1 AND lo.topic_id = $2", learner_id, tid)
        before = await conn.fetchval(
            "SELECT mastery_score FROM learner_topic_mastery WHERE learner_id = $1 AND topic_id = $2",
            learner_id, tid)
        after = before
        if not has_evidence:
            after = r["score"]
            await conn.execute(
                """
                INSERT INTO learner_topic_mastery (learner_id, topic_id, mastery_score)
                VALUES ($1, $2, $3)
                ON CONFLICT (learner_id, topic_id) DO UPDATE
                    SET mastery_score = EXCLUDED.mastery_score, last_assessed_at = now()
                """, learner_id, tid, after)
        await conn.execute(
            """
            INSERT INTO learner_events (learner_id, topic_id, source, evidence, misconception_code,
                                        weight, mastery_before, mastery_after)
            VALUES ($1, $2, 'diagnostic', $3, $4, 1.0, $5, $6)
            """, learner_id, tid,
            {"core": "attempt_correct", "easier": "attempt_partial", "none": "attempt_wrong"}[r["level"]],
            (r["misc"] or [None])[0], before, after)
    await conn.execute(
        """
        INSERT INTO diagnostic_results (learner_id, grade, bank_version, started_at, score_pct,
                                        first_try, topics, focus, answers)
        VALUES ($1, $2, $3, $4::timestamptz, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb)
        """, learner_id, grade, state["version"],
        datetime.datetime.fromisoformat(state["started_at"]), res["score_pct"], res["first_try"],
        json.dumps(res["topics"]), json.dumps(focus_topics), json.dumps(state["answers"]))


async def topic_weights(conn, grade: int) -> dict[str, float]:
    rows = await conn.fetch(
        "SELECT t.name, coalesce(t.duration_hours, 0) AS h FROM topics t "
        "JOIN grades g ON g.id = t.grade_id WHERE g.grade_number = $1", grade)
    return {r["name"]: float(r["h"] or 0) for r in rows}


async def latest(conn, learner_id: int) -> dict | None:
    row = await conn.fetchrow(
        "SELECT grade, topics, focus, score_pct, first_try, finished_at FROM diagnostic_results "
        "WHERE learner_id = $1 ORDER BY finished_at DESC LIMIT 1", learner_id)
    if not row:
        return None
    topics = json.loads(row["topics"])
    return {"grade": row["grade"], "topics": topics, "focus": json.loads(row["focus"]),
            "score_pct": float(row["score_pct"]), "first_try": row["first_try"],
            "answered": len(topics), "finished_at": row["finished_at"]}
