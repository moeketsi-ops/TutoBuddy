"""A week of Grade 8 homework on the ATP's current topic, on the real
WhatsApp path: what happens to pedagogy and mastery over seven days?

    # scripted learner (fixed answers; repeatable)
    docker compose run --rm -e GATEWAY_URL=http://gateway:8000 -e MOCKWA_URL=http://mockwa:8001 \\
        evals python -m evals.journey.week --learner scripted
    # AI-played learner (a cheap model with misconceptions that fade)
    docker compose run --rm -e GATEWAY_URL=http://gateway:8000 -e MOCKWA_URL=http://mockwa:8001 \\
        evals python -m evals.journey.week --learner ai

Day 0: sign-up and the 15-minute check-in (baseline; weak on Area and
Perimeter). Days 1-7: homework from evals/journey/homework_week_g8.json,
following the 2026 ATP (Grade 8 Term 4: Area and Perimeter, then Surface
Area and Volume). Between days the learner's clock moves on a day, so
sessions end, memory rolls into the digest and reviews fall due as they
would. Day 8: the check-in again (end-line).

Per day it records, from the database: topic and objective mastery, the
evidence written, strategies used, switches and whether they led to
progress, reviews, replies that stated the answer before the learner did,
and tokens, cost and speed. Writes week-<mode>-<time>/
report.md, days.csv and transcript.md (under evals/bench/results/journey/).

What this can and can't show: the learner is simulated, so the gain from
baseline to end-line is not evidence that Katlego teaches children well.
It shows whether the engine does what it should (adapts, reviews, tracks
mastery, stays on topic, stays cheap) over a realistic week. The pilot
measures real learning.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import json
import re
from pathlib import Path

from evals.bench import graders
from evals.journey.driver import Phone, is_error, learner_id, preflight, snapshot, time_travel
from evals.journey.full import answer_checkin

HERE = Path(__file__).parent
MAX_TURNS = 8


def _final_number(msg: str) -> float | None:
    """The last number in a learner's message, units stripped: "so 8+3=11,
    doubled is 22 cm" -> 22. Code's answer_check leaves prose to the model, so
    the week falls back to this to tell whether the AI learner got there."""
    from app.tutor import answer_check

    t = answer_check._UNITS.sub(" ", answer_check._normalise(msg))
    t = re.sub(r"\^\s*\d+", " ", t)
    nums = re.findall(r"-?\d+(?:\.\d+)?", t)
    return float(nums[-1]) if nums else None


def _verdict(problem: str, msg: str, answers: list[str]) -> str | None:
    from app.tutor import answer_check

    v = (answer_check.check(problem, msg) or {}).get("verdict")
    if v is None:
        n = _final_number(msg)
        if n is not None:
            right = any(abs(n - float(a.replace(" ", ""))) < 1e-6 for a in answers)
            v = "correct" if right else "wrong"
    return v


async def sim_checkin(phone: Phone, r: str, sim, grade: int) -> str:
    """The AI learner answers the check-in itself (baseline and end-line alike)."""
    from evals.journey.full import _bank

    bank = _bank(grade)
    while "Check-in done" not in r:
        head = next((l for l in r.splitlines() if l.startswith("*Check-in")), None)
        if head is None:
            break
        topic = head.split("·", 1)[1].strip(" *").replace(" (one more on this)", "")
        kind = "easier" if "one more on this" in head else "core"
        it = bank[(topic, kind)]
        q = it["stem"] + "\n" + "\n".join(f"{l}) {o}" for l, o in zip("ABCD", it["options"]))
        r = phone.say(await sim.answer_mcq(q))
    return r


def _first_correct(turns_truth: list[str]) -> bool:
    return len(turns_truth) > 1 and turns_truth[1] == "correct"


async def run_problem_scripted(phone: Phone, prob: dict) -> dict:
    replies, early = [], False
    reached = False
    for msg, truth in zip(prob["turns"], prob["truth"]):
        r = phone.say(msg)
        replies.append(r)
        reached = reached or (truth == "correct" and not is_error(r))
        if not reached and graders.leaks_answer(r, prob["answers"]):
            early = True
    return {"type": prob["type"], "problem": prob["turns"][0], "learner_turns": len(prob["turns"]) - 1,
            # the script says the learner got there; it only counts if Katlego actually replied
            "solved": reached, "first_try": _first_correct(prob["truth"]) and not any(map(is_error, replies)),
            "error_replies": sum(map(is_error, replies)),
            "attempts": sum(t in ("wrong", "partial", "correct") for t in prob["truth"]),
            "asked": prob["truth"].count("asked"), "early_answer": early}


async def run_problem_ai(phone: Phone, prob: dict, sim) -> dict:
    problem = prob["turns"][0]
    chat = [("learner", problem)]
    errors_before = phone.errors
    r = phone.say(problem)
    chat.append(("katlego", r))
    solved, first_try, attempts, asked, early = False, None, 0, 0, False
    for _ in range(MAX_TURNS):
        msg = await sim.reply(prob["type"], chat)
        chat.append(("learner", msg))
        verdict = _verdict(problem, msg, prob["answers"])
        if verdict in ("correct", "wrong", "step_forward"):
            attempts += 1
            if first_try is None:
                first_try = verdict == "correct"
        if "tell me" in msg.lower() or "answer" in msg.lower() and "just" in msg.lower():
            asked += 1
        r = phone.say(msg)
        chat.append(("katlego", r))
        if verdict == "correct":
            solved = True
            sim.record_solved(prob["type"])
            break
        if graders.leaks_answer(r, prob["answers"]):
            early = True
    return {"type": prob["type"], "problem": problem, "learner_turns": sum(1 for w, _ in chat if w == "learner") - 1,
            "solved": solved, "first_try": bool(first_try), "attempts": attempts, "asked": asked,
            "early_answer": early, "error_replies": phone.errors - errors_before}


async def run(mode: str, learner_model: str) -> Path:
    from app.db import get_pool

    spec = json.loads((HERE / "homework_week_g8.json").read_text())
    topics = spec["topics"]
    pool = await get_pool()
    phone = Phone()
    sim = None
    if mode == "ai":
        from evals.journey.sim_learner import SimLearner
        sim = SimLearner(spec["misconceptions"], name=spec["name"], grade=spec["grade"], model=learner_model)
    print(f"Homework week ({mode}), phone {phone.number}")
    if not await preflight():
        raise SystemExit(1)

    # Day 0: sign-up + baseline check-in
    for m in ("hi", "AGREE", spec["name"]):
        phone.say(m)
    r = phone.say(str(spec["grade"]))
    weak = set(spec["checkin"]["baseline_wrong"])
    pick = lambda it: (next(l for l in "ABCD" if l != it["answer"]) if it["topic"] in weak else it["answer"])  # noqa: E731
    if sim:
        r = await sim_checkin(phone, r, sim, spec["grade"])
    else:
        r, _ = answer_checkin(phone, r, spec["grade"], pick)
    async with pool.acquire() as conn:
        lid = await learner_id(conn, phone, spec["name"])
        day0 = await snapshot(conn, lid, topics)
    print(f"  day 0: check-in done; Area and Perimeter starts at {day0['topics'].get('Area and Perimeter')}")

    days, results = [], []
    for d in spec["days"]:
        async with pool.acquire() as conn:
            await time_travel(conn, lid, 1)
            start = await conn.fetchval("SELECT now()")
        phone.say("hi")
        probs = []
        for prob in d["problems"]:
            probs.append(await (run_problem_ai(phone, prob, sim) if sim else run_problem_scripted(phone, prob)))
        async with pool.acquire() as conn:
            snap = await snapshot(conn, lid, topics, since=start)
        days.append({"day": d["day"], "theme": d["theme"], "topic": d["topic"], "problems": probs, "snap": snap})
        a = snap["topics"].get("Area and Perimeter")
        print(f"  day {d['day']}: {d['theme']}: {sum(p['solved'] for p in probs)}/{len(probs)} solved, "
              f"Area and Perimeter mastery {a if a is None else round(a)}, cost ${snap['calls']['cost']:.4f}"
              + (f", {sum(p['error_replies'] for p in probs)} ERROR replies" if any(p['error_replies'] for p in probs) else ""))
        results += probs

    # Day 8: end-line check-in
    async with pool.acquire() as conn:
        await time_travel(conn, lid, 1)
    r = phone.say("CHECK-IN")
    if sim:
        r = await sim_checkin(phone, r, sim, spec["grade"])
    else:
        weak_end = set(spec["checkin"]["endline_wrong"])
        r, _ = answer_checkin(phone, r, spec["grade"],
                              lambda it: next(l for l in "ABCD" if l != it["answer"]) if it["topic"] in weak_end
                              else it["answer"])
    async with pool.acquire() as conn:
        checks = await conn.fetch("SELECT topics, score_pct FROM diagnostic_results WHERE learner_id = $1 "
                                  "ORDER BY finished_at", lid)
        final = await snapshot(conn, lid, topics)
        strat_stats = await conn.fetch("SELECT strategy, sum(tries) AS t, sum(successes) AS s FROM "
                                       "learner_strategy_stats WHERE learner_id = $1 GROUP BY 1 ORDER BY 2 DESC", lid)
        level_stats = await conn.fetch("SELECT * FROM learner_level_stats WHERE learner_id = $1", lid)
    return write_report(mode, spec, phone, day0, days, checks, final, strat_stats, level_stats, sim)


def write_report(mode, spec, phone, day0, days, checks, final, strat_stats, level_stats, sim) -> Path:
    # evals/bench/results is mounted from the host, so the report survives the container
    out = HERE.parent / "bench" / "results" / "journey" / f"week-{mode}-{datetime.datetime.now():%Y%m%d-%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in days:
        s, ps = d["snap"], d["problems"]
        ev = s["evidence"]
        sw = s["switches"]
        rows.append({
            "day": d["day"], "theme": d["theme"], "problems": len(ps),
            "solved": sum(p["solved"] for p in ps), "first_try": sum(p["first_try"] for p in ps),
            "learner_turns": sum(p["learner_turns"] for p in ps),
            "answer_early": sum(p["early_answer"] for p in ps),
            "area_perimeter": s["topics"].get("Area and Perimeter"),
            "surface_volume": s["topics"].get("Surface Area and Volume"),
            "objectives_covered": (s["objectives"].get(d["topic"]) or {}).get("covered", 0),
            "evidence_right": sum(v for k, v in ev.items() if k.endswith("attempt_correct") or k.endswith("explained_back")),
            "evidence_partial": sum(v for k, v in ev.items() if k.endswith("attempt_partial")),
            "evidence_wrong": sum(v for k, v in ev.items() if k.endswith("attempt_wrong")),
            "reviews": s["strategies"].get("RETRIEVAL_PRACTICE", 0),
            "switches": sum(n for _, _, n in sw),
            "switches_progress": sum(n for _, o, n in sw if o == "progress"),
            "top_strategy": max(s["strategies"], key=s["strategies"].get) if s["strategies"] else "",
            "calls": s["calls"]["n"], "tokens_in": s["calls"]["tin"], "tokens_out": s["calls"]["tout"],
            "cost_usd": round(s["calls"]["cost"], 5),
            "median_s": round((s["calls"]["lat"] or 0) / 1000, 1),
            "errors": s["calls"]["errors"] or 0,
            "error_replies": sum(p.get("error_replies", 0) for p in ps),
        })
    with open(out / "days.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def score(x):
        return "—" if x is None else f"{x:.0f}"

    base = json.loads(checks[0]["topics"]) if checks else {}
    end = json.loads(checks[-1]["topics"]) if len(checks) > 1 else {}
    total_cost = sum(r["cost_usd"] for r in rows)
    lines = [f"# Homework week: Grade 8 {', '.join(spec['topics'])} ({mode} learner)", "",
             f"{spec['atp']}. Learner: {spec['persona']}", "",
             "Simulated learner: this shows whether the engine behaves well over a week, not whether real "
             "children learn. The pilot measures that.", "",
             *([f"**{phone.errors} replies were \"something went wrong\"**: those turns got no tutoring and the "
                "problems they hit are not counted as solved. Check `docker compose logs worker --tail 80`.", ""]
               if phone.errors else []),
             "## Day by day", "",
             "| Day | Theme | Solved | First try | Learner msgs | Answer given early | Area & Perimeter mastery | "
             "Surface Area & Volume mastery | Objectives with evidence | Evidence right/partial/wrong | Reviews | "
             "Switches (led to progress) | Main strategy | Model calls | Cost | Median s |",
             "|" + "---|" * 16]
    lines.append(f"| 0 | Check-in | | | | | {score(day0['topics'].get('Area and Perimeter'))} | "
                 f"{score(day0['topics'].get('Surface Area and Volume'))} | | | | | | | | |")
    for r in rows:
        lines.append(
            f"| {r['day']} | {r['theme']} | {r['solved']}/{r['problems']} | {r['first_try']}/{r['problems']} | "
            f"{r['learner_turns']} | {r['answer_early']} | {score(r['area_perimeter'])} | "
            f"{score(r['surface_volume'])} | {r['objectives_covered']} | "
            f"{r['evidence_right']}/{r['evidence_partial']}/{r['evidence_wrong']} | {r['reviews']} | "
            f"{r['switches']} ({r['switches_progress']}) | {r['top_strategy'].lower().replace('_', ' ')} | "
            f"{r['calls']} | ${r['cost_usd']:.4f} | {r['median_s']} |")
    lines += ["", "## Check-in: baseline (day 0) and end-line (day 8)", "",
              "| Topic | Baseline | End-line |", "|---|---|---|"]
    for t in sorted(set(base) | set(end)):
        b, e = base.get(t, {}), end.get(t, {})
        if b.get("score") != e.get("score") or t in spec["topics"]:
            lines.append(f"| {t} | {score(b.get('score'))} | {score(e.get('score'))} |")
    if checks:
        lines.append(f"| **Overall** | {checks[0]['score_pct']}% | "
                     f"{checks[-1]['score_pct'] if len(checks) > 1 else '—'}% |")
    lines += ["", "## Which strategies worked for this learner", "",
              "| Strategy | Tries | Led to a right answer |", "|---|---|---|"]
    for s in strat_stats:
        lines.append(f"| {s['strategy'].lower().replace('_', ' ')} | {s['t']} | {s['s']} |")
    if level_stats:
        lv: dict[str, list[int]] = {}
        for r in level_stats:
            x = lv.setdefault(r["cpa_level"], [0, 0])
            x[0] += r["successes"]
            x[1] += r["tries"]
        lines += ["", "Concrete-pictorial-abstract levels (progress / tries): " + "; ".join(
            f"{k} {v[0]}/{v[1]}" for k, v in sorted(lv.items()))]
    lines += ["", "## Cost", "",
              f"- Katlego's model calls over the week: ${total_cost:.4f} for {sum(r['calls'] for r in rows)} calls "
              f"({sum(r['learner_turns'] for r in rows) + sum(r['problems'] for r in rows)} learner messages).",
              f"- Errors or cut-off replies: {sum(r['errors'] for r in rows)}."]
    if sim:
        lines.append(f"- The AI learner's own calls (not Katlego's cost): ${sim.cost:.4f}, {sim.calls} calls "
                     f"on {sim.model}.")
    lines += ["", "## What to read", "",
              "- Mastery should climb from the check-in's 20 as days go by, and dip less on later days.",
              "- Switches that led to progress show the 3-turn rule helping; switches with no progress are "
              "the transcripts to read first.",
              "- 'Answer given early' should be 0; any other number is a transcript to read.",
              "- Reviews should appear at the start of days after a weak day (spaced review).",
              "", "Transcript: transcript.md · numbers: days.csv"]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    (out / "transcript.md").write_text(f"# Transcript ({mode})\n\n```\n{phone.transcript()}\n```\n")
    print(f"\nReport: {out / 'report.md'}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--learner", choices=["scripted", "ai"], default="scripted")
    ap.add_argument("--learner-model", default="openai/gpt-5.4-nano",
                    help="OpenRouter model that plays the learner (ai mode)")
    args = ap.parse_args()
    asyncio.run(run(args.learner, args.learner_model))


if __name__ == "__main__":
    main()
