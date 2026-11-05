"""Per-learner usage of the model during the pilot: what each learner did,
how many tokens and dollars it took, and where the spend goes.

    python -m app.reports.usage                       # last 7 days
    python -m app.reports.usage --days 30 --fx 16.02  # rand too
    python -m app.reports.usage --learner 42 --csv usage.csv

In Docker: docker compose run --rm evals python -m app.reports.usage

Reads llm_calls (every model call, written by app/adapters/ledger.py with
the active learner), conversation_log (every message in and out, with its
intent), diagnostic_results and paper_attempts. Read-only. Learner names
are nicknames only; no phone numbers are printed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import statistics

# conversation_log intent -> what the learner was doing
ACTIVITY = {
    "homework": "tutoring", "paper_help": "tutoring", "quiz": "practice", "quiz_answer": "practice",
    "checkin": "check-in", "paper": "papers", "prep": "papers", "test": "test prep", "squad": "squads",
    "smalltalk": "other", "admin": "other", "safety": "other",
}
CALL_LABEL = {
    "socratic_reply": "tutoring reply", "classify_intent": "routing", "practice_question": "practice question",
    "grade_practice_answer": "practice marking", "mark_against_memo": "paper marking",
    "photo_reply": "homework photo", "direct_answer": "eval only",
}


def _pct(a: float, b: float) -> str:
    return f"{100 * a / b:.0f}%" if b else "—"


def _money(x: float | None, fx: float | None = None) -> str:
    if x is None:
        return "—"
    s = f"${x:.4f}" if x < 1 else f"${x:.2f}"
    return s + (f" (R{x * fx:.2f})" if fx else "")


async def collect(conn, since: datetime.datetime, learner: int | None = None) -> dict:
    lf = "AND learner_id = $2" if learner else ""
    args = [since] + ([learner] if learner else [])
    calls = [dict(r) for r in await conn.fetch(
        f"""
        SELECT learner_id, call, model, coalesce(prompt_tokens, 0) AS tin,
               coalesce(completion_tokens, 0) AS tout, coalesce(reasoning_tokens, 0) AS treason,
               coalesce(cost_usd, 0)::float AS cost, latency_ms, finish_reason, state_valid,
               strategy, estimated, created_at::date AS day,
               coalesce(cached_tokens, 0) AS tcached
        FROM llm_calls WHERE created_at >= $1 {lf}
        """, *args)]
    msgs = [dict(r) for r in await conn.fetch(
        f"""
        SELECT learner_id, direction, intent, created_at::date AS day
        FROM conversation_log WHERE created_at >= $1 {lf}
        """, *args)]
    learners = {r["id"]: dict(r) for r in await conn.fetch(
        "SELECT id, nickname, grade, created_at FROM learners")}
    checkins = {r["learner_id"]: r["n"] for r in await conn.fetch(
        "SELECT learner_id, count(*) AS n FROM diagnostic_results GROUP BY 1")}
    papers = {r["learner_id"]: (r["n"], r["awarded"], r["out_of"]) for r in await conn.fetch(
        "SELECT learner_id, count(*) AS n, sum(awarded) AS awarded, sum(out_of) AS out_of "
        "FROM paper_attempts GROUP BY 1")}
    return {"calls": calls, "msgs": msgs, "learners": learners, "checkins": checkins, "papers": papers}


def per_learner(data: dict) -> list[dict]:
    rows: dict[int, dict] = {}

    def row(lid):
        if lid not in rows:
            info = data["learners"].get(lid, {})
            rows[lid] = {"learner_id": lid, "nickname": info.get("nickname", "?"), "grade": info.get("grade"),
                         "days_active": set(), "messages": 0, "calls": 0, "tokens_in": 0, "tokens_out": 0,
                         "tokens_reasoning": 0, "cost_usd": 0.0, "latency": [], "errors": 0,
                         "unparsed": 0, "activity": {}, "by_call": {}}
        return rows[lid]

    for m in data["msgs"]:
        if m["learner_id"] is None:
            continue
        r = row(m["learner_id"])
        if m["direction"] == "inbound":
            r["messages"] += 1
            r["days_active"].add(m["day"])
        elif m["intent"]:
            # the reply's intent says what the learner's message was for
            act = ACTIVITY.get(m["intent"], "tutoring")
            r["activity"][act] = r["activity"].get(act, 0) + 1
    for c in data["calls"]:
        if c["learner_id"] is None:
            continue
        r = row(c["learner_id"])
        r["calls"] += 1
        r["tokens_in"] += c["tin"]
        r["tokens_out"] += c["tout"]
        r["tokens_reasoning"] += c["treason"]
        r["cost_usd"] += c["cost"]
        if c["latency_ms"]:
            r["latency"].append(c["latency_ms"])
        if c["finish_reason"] in ("error", "length"):
            r["errors"] += 1
        if c["call"] == "socratic_reply" and c["state_valid"] is False:
            r["unparsed"] += 1
        k = CALL_LABEL.get(c["call"], c["call"])
        b = r["by_call"].setdefault(k, [0, 0.0])
        b[0] += 1
        b[1] += c["cost"]
    out = []
    for r in rows.values():
        r["days_active"] = len(r["days_active"])
        r["cost_per_message"] = r["cost_usd"] / r["messages"] if r["messages"] else None
        r["median_latency_s"] = statistics.median(r["latency"]) / 1000 if r["latency"] else None
        r["checkins"] = data["checkins"].get(r["learner_id"], 0)
        n, a, o = data["papers"].get(r["learner_id"], (0, 0, 0))
        r["papers"], r["paper_pct"] = n, (100 * a / o if o else None)
        del r["latency"]
        out.append(r)
    return sorted(out, key=lambda r: -r["cost_usd"])


def report(data: dict, rows: list[dict], days: int, fx: float | None) -> str:
    calls = data["calls"]
    total = sum(c["cost"] for c in calls)
    msgs_in = sum(1 for m in data["msgs"] if m["direction"] == "inbound")
    learners = [r for r in rows if r["messages"] or r["calls"]]
    lines = [f"# Katlego usage, last {days} days\n"]
    lines.append(f"- Active learners: {len(learners)} · messages in: {msgs_in} · model calls: {len(calls)}")
    lines.append(f"- Tokens: {sum(c['tin'] for c in calls):,} in, {sum(c['tout'] for c in calls):,} out "
                 f"({sum(c['treason'] for c in calls):,} of them hidden reasoning)")
    tin_all, cached_all = sum(c["tin"] for c in calls), sum(c.get("tcached", 0) for c in calls)
    lines.append(f"- Prompt tokens served from cache: {cached_all:,} of {tin_all:,} ({_pct(cached_all, tin_all)})"
                 " · see `python -m app.reports.cache_eval` for what caching could save")
    lines.append(f"- Model cost: {_money(total, fx)}"
                 + (f" · per message {_money(total / msgs_in, fx)}" if msgs_in else ""))
    if learners:
        costs = sorted(r["cost_usd"] for r in learners)
        p90 = costs[min(len(costs) - 1, int(0.9 * len(costs)))]
        lines.append(f"- Per learner over the period: median {_money(statistics.median(costs), fx)}, "
                     f"90th percentile {_money(p90, fx)}, highest {_money(costs[-1], fx)}")
        if days:
            month = statistics.median(costs) * 30 / days
            lines.append(f"- Median learner, scaled to 30 days: {_money(month, fx)}")
    unpriced = sum(1 for c in calls if c["estimated"])
    if unpriced:
        lines.append(f"- {unpriced} calls were stub/estimated (no real cost)")

    by_call: dict[str, list] = {}
    for c in calls:
        k = CALL_LABEL.get(c["call"], c["call"])
        b = by_call.setdefault(k, [0, 0, 0, 0, 0.0, []])
        b[0] += 1
        b[1] += c["tin"]
        b[2] += c["tout"]
        b[3] += c["treason"]
        b[4] += c["cost"]
        if c["latency_ms"]:
            b[5].append(c["latency_ms"])
    lines.append("\n## Where the spend goes\n")
    lines.append("| Call | Calls | Avg tokens in | Avg tokens out | Avg reasoning | Cost | Share | Median s |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for k, (n, tin, tout, tr, cost, lat) in sorted(by_call.items(), key=lambda kv: -kv[1][4]):
        lines.append(f"| {k} | {n} | {tin // max(n, 1)} | {tout // max(n, 1)} | {tr // max(n, 1)} | "
                     f"{_money(cost)} | {_pct(cost, total)} | "
                     f"{statistics.median(lat) / 1000:.1f} |" if lat else
                     f"| {k} | {n} | {tin // max(n, 1)} | {tout // max(n, 1)} | {tr // max(n, 1)} | "
                     f"{_money(cost)} | {_pct(cost, total)} | — |")

    lines.append("\n## Per learner\n")
    lines.append("| Learner | Grade | Days | Messages | Doing | Calls | Tokens in/out | Cost | Per message | "
                 "Check-ins | Papers | Errors |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in learners:
        doing = ", ".join(f"{k} {v}" for k, v in sorted(r["activity"].items(), key=lambda kv: -kv[1])[:3])
        paper = f"{r['papers']} ({r['paper_pct']:.0f}%)" if r["papers"] and r["paper_pct"] is not None else str(r["papers"])
        lines.append(f"| {r['nickname']} (#{r['learner_id']}) | {r['grade']} | {r['days_active']} | {r['messages']} | "
                     f"{doing or '—'} | {r['calls']} | {r['tokens_in']:,}/{r['tokens_out']:,} | "
                     f"{_money(r['cost_usd'], fx)} | {_money(r['cost_per_message'])} | {r['checkins']} | "
                     f"{paper} | {r['errors'] + r['unparsed']} |")

    lines.append("\n## By day\n")
    days_map: dict = {}
    for m in data["msgs"]:
        if m["direction"] == "inbound":
            days_map.setdefault(m["day"], [0, 0, 0.0])[0] += 1
    for c in calls:
        d = days_map.setdefault(c["day"], [0, 0, 0.0])
        d[1] += 1
        d[2] += c["cost"]
    lines.append("| Day | Messages in | Model calls | Cost |")
    lines.append("|---|---|---|---|")
    for d in sorted(days_map):
        m, n, cost = days_map[d]
        lines.append(f"| {d} | {m} | {n} | {_money(cost, fx)} |")

    lines.append("\n## What to look at\n")
    lines += insights(calls, learners, by_call, total)
    return "\n".join(lines)


def insights(calls, learners, by_call, total) -> list[str]:
    out = []
    if not calls:
        return ["- No model calls in this period."]
    if total > 0:
        top = max(by_call.items(), key=lambda kv: kv[1][4])
        out.append(f"- {top[0]} is {_pct(top[1][4], total)} of the spend: tune its prompt and model first.")
    else:
        out.append("- No billed cost in this period (stub or unpriced calls): token counts are estimates.")
    tut = by_call.get("tutoring reply")
    if tut and tut[0]:
        avg_in = tut[1] / tut[0]
        out.append(f"- A tutoring reply reads {avg_in:.0f} prompt tokens on average"
                   + (" (over 1,500: check the notes, memory and objectives sent)" if avg_in > 1500 else "") + ".")
        if tut[3] and tut[3] > 0.5 * tut[2]:
            out.append(f"- Hidden reasoning is {_pct(tut[3], tut[2])} of tutoring output tokens: try a lower effort.")
    errs = sum(1 for c in calls if c["finish_reason"] in ("error", "length"))
    if errs:
        out.append(f"- {errs} calls ended in an error or ran out of tokens ({_pct(errs, len(calls))}); "
                   "each one is a learner who got the fallback message.")
    unparsed = sum(1 for c in calls if c["call"] == "socratic_reply" and c["state_valid"] is False)
    if unparsed:
        out.append(f"- {unparsed} tutoring replies came back without a usable state: no mastery evidence "
                   "was recorded for those turns.")
    if learners:
        costs = sorted(r["cost_usd"] for r in learners)
        p90 = costs[min(len(costs) - 1, int(0.9 * len(costs)))]
        heavy = [r for r in learners if r["cost_usd"] >= p90 and r["cost_usd"] > 0]
        if heavy and len(learners) >= 5:
            names = ", ".join(f"{r['nickname']} (#{r['learner_id']}, {r['messages']} messages)" for r in heavy[:5])
            out.append(f"- Top 10% by cost: {names}. Check whether that is heavy use or long, stuck problems.")
        no_checkin = [r for r in learners if not r["checkins"]]
        if no_checkin:
            out.append(f"- {len(no_checkin)} of {len(learners)} active learners have not finished the check-in.")
        quiet = [r for r in learners if r["days_active"] <= 1 and r["messages"] <= 3]
        if quiet:
            out.append(f"- {len(quiet)} learners sent 3 messages or fewer: follow up with their pilot partner.")
    return out


def write_csv(rows: list[dict], path: str) -> None:
    keys = ["learner_id", "nickname", "grade", "days_active", "messages", "calls", "tokens_in", "tokens_out",
            "tokens_reasoning", "cost_usd", "cost_per_message", "median_latency_s", "errors", "unparsed",
            "checkins", "papers", "paper_pct"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys + ["activity", "cost_by_call"])
        for r in rows:
            w.writerow([r[k] for k in keys]
                       + ["; ".join(f"{k}={v}" for k, v in r["activity"].items()),
                          "; ".join(f"{k}={v[1]:.5f}" for k, v in r["by_call"].items())])


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--since", help="YYYY-MM-DD (overrides --days)")
    ap.add_argument("--learner", type=int)
    ap.add_argument("--csv", help="also write per-learner rows to this CSV file")
    ap.add_argument("--out", help="also write the report to this markdown file")
    ap.add_argument("--fx", type=float, help="rand per US dollar, to show ZAR")
    args = ap.parse_args()
    from app.db import get_pool

    now = datetime.datetime.now(datetime.timezone.utc)
    since = (datetime.datetime.fromisoformat(args.since).replace(tzinfo=datetime.timezone.utc)
             if args.since else now - datetime.timedelta(days=args.days))
    days = max(1, (now - since).days)
    pool = await get_pool()
    async with pool.acquire() as conn:
        data = await collect(conn, since, args.learner)
    rows = per_learner(data)
    text = report(data, rows, days, args.fx)
    print(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nWrote {len(rows)} learners to {args.csv}")


if __name__ == "__main__":
    asyncio.run(main())
