"""Run bake-off suites against candidate models through the real Katlego code.

    python -m evals.bench.run --stage dry                     # stub only, free
    python -m evals.bench.run --stage pilot                   # prints the plan and cost estimate, then stops
    python -m evals.bench.run --stage pilot --yes             # actually runs (paid)
    python -m evals.bench.run --stage sweep --suites tutoring --models deepseek/deepseek-v4-flash --yes

Results: evals/bench/results/<stage>/<suite>/<variant>/results.jsonl (one row
per case and repeat, written as each finishes; reruns resume) and errors.jsonl
(harness/API failures, retried on resume). A variant is model@effort.
"""

import argparse
import asyncio
import contextlib
import json
import statistics
import sys
import time
import tomllib
from pathlib import Path

from app.adapters import llm, router
from app.config import settings
from app.tutor import engine, rag
from evals.bench import graders, judge, prices

HERE = Path(__file__).parent
RESULTS = HERE / "results"
SUITES = ("router", "maths", "tutoring", "marking", "practice", "conversations", "homework_day")
JUDGED = ("tutoring", "practice", "conversations")

# Stage presets; every value can be overridden on the command line.
STAGES = {
    "dry":     {"limit": None, "reps": 1, "router_efforts": [""],                         "reasoner_efforts": [""]},
    "pilot":   {"limit": 5,    "reps": 1, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
    "screen":  {"limit": None, "reps": 1, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
    "sweep":   {"limit": None, "reps": 3, "router_efforts": ["none", "minimal", "low"],   "reasoner_efforts": ["none", "low", "medium", "high"]},
    "confirm": {"limit": None, "reps": 3, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
    # 3 Nov: the bake-off fixes re-checked on the 31 Oct shortlist (all cases, effort low)
    "recheck": {"limit": None, "reps": 1, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
    # 5 Nov: again, after the opener-label and c08 grader fixes
    "recheck2": {"limit": None, "reps": 1, "router_efforts": ["none"],                    "reasoner_efforts": ["low"]},
    # 5 Nov: the two AI judges on the finalists (6 cases per grade; conversations run with --limit 0)
    "judged":   {"limit": 6,    "reps": 1, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
}

# Rough tokens per call, used ONLY to quote the pilot before any measurement
# exists. Every later quote comes from measured pilot rows.
GUESS_TOKENS = {"router": (350, 5), "maths": (1400, 500), "tutoring": (1800, 250),
                "marking": (700, 80), "practice": (2200, 150),
                # a whole scripted conversation: ~4 turns x (1,300 in, 230 out)
                "conversations": (5200, 920),
                # a learner's day: ~7 problems x ~5 turns x (1,300 in, 230 out)
                "homework_day": (45500, 8050)}
# Twilio's WhatsApp fee per message, in or out, on top of Meta's
# (twilio.com/en-us/whatsapp/pricing, Sept 2026). Meta's own service-message
# fee for South Africa is not confirmed, so it is left out.
TWILIO_USD_PER_MESSAGE = 0.005
GUESS_REASONING = {"": 0, "none": 0, "minimal": 300, "low": 800, "medium": 2000, "high": 4000}
GUESS_JUDGE = (1200, 2500)  # per judge call; medium effort reasoning counts as output
GUESS_JUDGE_CONV = (3000, 3500)  # a whole conversation per judge call


def load_cases(suite: str) -> list[dict]:
    lines = (HERE / "cases" / f"{suite}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def select_cases(suite: str, limit: int | None, grades: set[int] | None, ids: set[str] | None = None) -> list[dict]:
    """Cases for a run: only the chosen grades (router cases have no grade and
    always stay), and `limit` applies per grade so a light run samples every
    grade instead of just the first one in the file."""
    cases = [c for c in load_cases(suite) if grades is None or c.get("grade") is None or c["grade"] in grades]
    if ids:
        return [c for c in cases if c["id"] in ids]
    if not limit:
        return cases
    # Round-robin over case kinds (tags[0]) within each grade, so a light run
    # covers off-grade and give-me-the-answer cases instead of only the easy
    # ones listed first. Marking's tags[0] is the verdict, so its manipulation
    # cases need --cases.
    out = []
    for g in dict.fromkeys(c.get("grade") for c in cases):
        by_kind: dict = {}
        for c in cases:
            if c.get("grade") == g:
                by_kind.setdefault((c.get("tags") or [""])[0], []).append(c)
        queues, picked = list(by_kind.values()), []
        while len(picked) < limit and any(queues):
            for q in queues:
                if q and len(picked) < limit:
                    picked.append(q.pop(0))
        out += picked
    return out


def config() -> dict:
    return tomllib.loads((HERE / "candidates.toml").read_text())


def variant_name(model: dict, effort: str) -> str:
    """Result folder name. No ':' (Windows can't check out such paths):
    groq:openai/gpt-oss-120b -> groq_openai__gpt-oss-120b."""
    return f"{model['slug'].replace(':', '_').replace('/', '__')}@{effort or 'default'}"


def is_paid(model: dict) -> bool:
    return model.get("route", "openrouter") != "stub"


_FIELDS = ("groq_router_model", "groq_reasoner_model", "llm_provider", "reasoner_provider", "router_provider", "openrouter_router_model",
           "openrouter_reasoner_model", "openrouter_vision_model", "router_model", "reasoner_model",
           "router_effort", "reasoner_effort", "openrouter_provider")


@contextlib.contextmanager
def use_variant(model: dict, effort: str, tier: str):
    """Point the app's settings at one model + effort for the duration of a
    variant. Variants run one at a time, so this can't leak between them."""
    saved = {f: getattr(settings, f) for f in _FIELDS}
    route = model.get("route", "openrouter")
    try:
        settings.reasoner_provider = settings.router_provider = ""
        settings.router_effort = settings.reasoner_effort = ""
        settings.openrouter_provider = model.get("host", "")
        if route == "stub":
            settings.llm_provider = "stub"
        elif route == "jev":
            settings.llm_provider, settings.router_provider = "stub", "jev"
        elif route == "groq":
            settings.llm_provider = "groq"
            settings.groq_router_model = settings.groq_reasoner_model = model.get("model_id", model["slug"])
        elif route == "anthropic":
            settings.llm_provider = "anthropic"
            settings.router_model = settings.reasoner_model = model.get("model_id", model["slug"])
        else:
            settings.llm_provider = "openrouter"
            settings.openrouter_router_model = settings.openrouter_reasoner_model = model["slug"]
            settings.openrouter_vision_model = model["slug"]
        if tier == "router":
            settings.router_effort = effort
        else:
            settings.reasoner_effort = effort
        yield
    finally:
        for f, v in saved.items():
            setattr(settings, f, v)


# ── Suites: each calls the production entry point and grades the output ──────

async def _router(case, ctx):
    label = await router.classify_intent(case["text"])
    return {"output": label, "grade": {"correct": float(label == case["intent"])}}


async def _maths(case, ctx):
    out = await engine.eval_answer(case["question"], case["grade"])
    return {"output": out, "grade": {"correct": float(graders.answer_matches(out, case["answers"]))}}


async def _tutoring(case, ctx):
    reply = await engine.tutor_reply(case["message"], case["grade"], None)
    grade = {
        "within_120_words": float(graders.word_count(reply) <= 120),
        "asks_question": float(graders.asks_question(reply)),
        "has_link": float(graders.has_link(reply)),
    }
    if case["answers"]:
        grade["leaks_answer"] = float(graders.leaks_answer(reply, case["answers"]))
    out = {"output": reply, "grade": grade}
    if ctx["judges"]:
        out["judge"] = await judge.judge_tutoring(ctx["judges"], case, reply)
    return out


async def _marking(case, ctx):
    res = await llm.grade_practice_answer(case["question"], case["model_answer"],
                                          case["learner_answer"], case["grade"])
    return {"output": f"{res['correctness']}: {res['feedback']}", "pred": res["correctness"],
            "grade": graders.marking_outcome(case["expected"], res["correctness"])}


async def _practice(case, ctx):
    excerpts = await rag.get_past_paper_excerpts(case["topic"], case["grade"])
    res = await llm.practice_question(case["topic"], case["grade"], case["band"], excerpts)
    parsed = bool(res.get("model_answer")) and bool(res.get("question", "").strip())
    out = {"output": f"QUESTION: {res.get('question')}\nFINAL_ANSWER: {res.get('model_answer')}",
           "grade": {"parsed": float(parsed)}}
    if ctx["judges"] and parsed:
        out["judge"] = await judge.judge_practice(ctx["judges"], case, res["question"], res["model_answer"])
    return out


# ── Multi-turn: memory + STATE line + pedagogy (moeketsi/memory-pedagogy) ────
# Each case is a scripted learner: a fixed list of messages with a truth
# label per message. A throwaway learner is created per case so the real
# memory window, mastery writes and strategy choice run exactly as live, then
# everything is erased. Scores what single-turn suites can't see:
#   state_valid      every reply carried a parseable state (JSON or STATE line)
#   structured       the provider honoured the JSON schema (no fallback)
#   strategy_follow  the reply used the strategy (or fallback) code chose
#   judged_right     the model's ev label matched the truth label
#   leak_early       the final answer appeared before the learner reached it
#   on_problem       the working problem survived every follow-up turn

_TRUTH = {"none": {"none"}, "wrong": {"attempt_wrong", "attempt_partial"},
          "partial": {"attempt_partial", "attempt_correct"}, "correct": {"attempt_correct"},
          "asked": {"asked_for_answer"}, "explain": {"explained_back", "attempt_correct"}}


async def _conversations(case, ctx):
    from app.adapters import ledger
    from app.db import get_pool
    from app.tutor import memory

    pool = await get_pool()
    async with pool.acquire() as conn:
        account = await conn.fetchval("INSERT INTO accounts DEFAULT VALUES RETURNING id")
        learner = await conn.fetchval(
            "INSERT INTO learners (account_id, nickname, grade) VALUES ($1, $2, $3) RETURNING id",
            account, case.get("name", "Bench"), case["grade"])
    turns, transcript, pairs = [], [], []
    try:
        reached = False
        for msg, truth in zip(case["turns"], case["truth"]):
            reply = await engine.tutor_reply(msg, case["grade"], learner, case.get("name"))
            info = engine.last_turn.get() or {}
            st, d = info.get("state") or {}, info.get("decision") or {}
            # the learner has reached the answer once they say it, even when the
            # script calls it "partial" (c08: "28" before "28 square cm")
            reached = reached or truth in ("correct", "explain") or info.get("code_check") == "correct"
            turns.append({
                "valid": bool(st.get("valid")),
                "followed": st.get("strategy") in (d.get("strategy"), d.get("fallback")),
                "judged": None if truth == "any" or msg == case["turns"][0]
                          else st.get("ev") in _TRUTH.get(truth, set()),
                "leak": (not reached and not d.get("reveal")
                         and graders.leaks_answer(reply, case["answers"])),
                "problem": info.get("problem"),
                "structured": info.get("output_mode") == "json",
                "strategy": d.get("strategy"), "ev": st.get("ev"),
                "level": info.get("level"), "switch": info.get("switch"),
                "code_check": info.get("code_check"),
                "guard": info.get("leak_guard"),
                "topic": (info.get("topic") or {}).get("name"),
            })
            tag = f"{d.get('strategy')} / {info.get('level')} / ev={st.get('ev')}"
            if info.get("switch"):
                tag += f" / SWITCH {info['switch']} ({info.get('chosen_by')})"
            if info.get("code_check"):
                tag += f" / code={info['code_check']}"
            if info.get("leak_guard"):
                tag += f" / LEAK GUARD {info['leak_guard']}"
            transcript.append(f"L: {msg}\nK [{tag}]: {reply}")
            pairs.append((msg, reply))
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM llm_calls WHERE learner_id = $1", learner)
            await conn.execute("DELETE FROM accounts WHERE id = $1", account)
        await memory.forget(learner)
        ledger.current_learner.set(None)

    judged = [t["judged"] for t in turns if t["judged"] is not None]
    first_problem = turns[0]["problem"]
    grade = {
        "state_valid": sum(t["valid"] for t in turns) / len(turns),
        # share of turns where the schema-constrained JSON came back (vs the
        # prompt-only JSON or STATE-line fallbacks)
        "structured": sum(t["structured"] for t in turns) / len(turns),
        "strategy_follow": sum(t["followed"] for t in turns) / len(turns),
        "judged_right": (sum(judged) / len(judged)) if judged else None,
        "leak_early": float(any(t["leak"] for t in turns)),
        "on_problem": float(bool(first_problem) and all(
            t["problem"] in (first_problem, None) for t in turns[1:])),
        "code_checked": sum(bool(t["code_check"]) for t in turns[1:]) / max(1, len(turns) - 1),
        # leak guard: share of turns where the reply had to be rewritten or masked
        "guard_rewrote": sum(t["guard"] == "rewritten" for t in turns) / len(turns),
        "guard_masked": sum(t["guard"] == "masked" for t in turns) / len(turns),
    }
    # CPA cases say when the switch should land (1-based turn) or that none should.
    switches = [i + 1 for i, t in enumerate(turns) if t["switch"]]
    if case.get("expect_switches"):
        kinds = [t["switch"] for t in turns if t["switch"]]
        grade["switch_sequence_ok"] = float(kinds[:len(case["expect_switches"])] == case["expect_switches"])
    if case.get("no_switch"):
        grade["switched_ok"] = float(not switches)
    elif case.get("switch_by"):
        grade["switched_ok"] = float(bool(switches) and switches[0] <= case["switch_by"])
    out = {"output": "\n\n".join(transcript), "grade": grade, "topic": turns[0]["topic"],
           "strategies": [t["strategy"] for t in turns], "evs": [t["ev"] for t in turns],
           "levels": [t["level"] for t in turns], "switches": switches}
    if ctx["judges"]:
        out["judge"] = await judge.judge_conversation(ctx["judges"], case, pairs)
    return out


# ── A learner's homework day (CPA spec section 8) ────────────────────────────
# One scripted learner works through ~7 maths problems in one sitting, so
# the profile built on early problems (strategy and level stats) is used on
# later ones, as live. run_case already totals calls, tokens, reasoning,
# cost and seconds for the whole day; this adds per-problem turns, switches
# and whether each problem was solved, plus the WhatsApp message count and
# Twilio's fee for the same day.

async def _homework_day(case, ctx):
    from app.adapters import ledger
    from app.db import get_pool
    from app.tutor import memory

    pool = await get_pool()
    async with pool.acquire() as conn:
        account = await conn.fetchval("INSERT INTO accounts DEFAULT VALUES RETURNING id")
        learner = await conn.fetchval(
            "INSERT INTO learners (account_id, nickname, grade) VALUES ($1, $2, $3) RETURNING id",
            account, case.get("name", "Bench"), case["grade"])
    problems, transcript, judged, leaks, checked, seconds = [], [], [], [], [], []
    try:
        for n, prob in enumerate(case["problems"], 1):
            transcript.append(f"### Problem {n}: {prob['turns'][0]}")
            reached, switches, levels, solved = False, 0, [], False
            for i, (msg, truth) in enumerate(zip(prob["turns"], prob["truth"])):
                t0 = time.perf_counter()
                reply = await engine.tutor_reply(msg, case["grade"], learner, case.get("name"))
                seconds.append(time.perf_counter() - t0)
                info = engine.last_turn.get() or {}
                st, d = info.get("state") or {}, info.get("decision") or {}
                reached = reached or truth in ("correct", "explain") or \
                    (engine.last_turn.get() or {}).get("code_check") == "correct"
                if i and truth != "any":
                    judged.append(st.get("ev") in _TRUTH.get(truth, set()))
                    checked.append(bool(info.get("code_check")))
                leaks.append(not reached and not d.get("reveal")
                             and graders.leaks_answer(reply, prob.get("answers", [])))
                switches += bool(info.get("switch"))
                levels.append(info.get("level"))
                solved = solved or bool(truth == "correct" and (info.get("problem") is None or d.get("bridge")))
                transcript.append(f"L: {msg}\nK [{d.get('strategy')} / {info.get('level')}"
                                  f"{' / SWITCH ' + info['switch'] if info.get('switch') else ''}]: {reply}")
            problems.append({"turns": len(prob["turns"]), "switches": switches, "solved": solved,
                             "levels": levels})
        async with pool.acquire() as conn:
            profile = await conn.fetch(
                "SELECT cpa_level, sum(tries) AS tries, sum(successes) AS successes "
                "FROM learner_level_stats WHERE learner_id = $1 GROUP BY cpa_level", learner)
            log_rows = await conn.fetch(
                "SELECT switch, chosen_by, outcome FROM pedagogy_decisions WHERE learner_id = $1",
                learner)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM llm_calls WHERE learner_id = $1", learner)
            await conn.execute("DELETE FROM accounts WHERE id = $1", account)
        await memory.forget(learner)
        ledger.current_learner.set(None)

    turns = sum(p["turns"] for p in problems)
    messages = 2 * turns  # each learner message gets one reply
    grade = {
        "problems": len(problems),
        "turns_per_problem": round(turns / max(1, len(problems)), 2),
        "switches_per_problem": round(sum(p["switches"] for p in problems) / max(1, len(problems)), 2),
        "solved_share": sum(p["solved"] for p in problems) / max(1, len(problems)),
        "judged_right": (sum(judged) / len(judged)) if judged else None,
        "code_checked": (sum(checked) / len(checked)) if checked else None,
        "leak_early": float(any(leaks)),
        "seconds_per_reply": statistics.median(seconds) if seconds else None,
        "wa_messages": messages,
        "twilio_usd": round(messages * TWILIO_USD_PER_MESSAGE, 4),
        "switches_logged": len(log_rows),
        "switches_with_progress": sum(r["outcome"] == "progress" for r in log_rows),
    }
    return {"output": "\n\n".join(transcript), "grade": grade, "problems": problems,
            "level_profile": {r["cpa_level"]: [r["tries"], r["successes"]] for r in profile}}


RUNNERS = {"router": _router, "maths": _maths, "tutoring": _tutoring, "marking": _marking, "practice": _practice,
           "conversations": _conversations, "homework_day": _homework_day}


# ── Checks that protect the comparison ───────────────────────────────────────

def _same_model(requested: str, served: str | None) -> bool:
    if not served:
        return True
    r, s = requested.split(":")[0].lower(), served.split(":")[0].lower()
    return s.startswith(r) or r.split("/")[-1] in s


class Skip(Exception):
    """A harness-side failure: logged to errors.jsonl and retried on resume."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


async def run_case(suite, case, rep, model, effort, ctx, timeout_s):
    started = time.perf_counter()
    with llm.capture_calls() as calls:
        try:
            out = await asyncio.wait_for(RUNNERS[suite](case, ctx), timeout_s)
            status = "ok"
        except asyncio.TimeoutError:
            raise Skip("timeout", f"over {timeout_s}s")
        except RuntimeError as exc:  # the app raises this for an empty model reply
            if "empty" not in str(exc):
                raise Skip("app_error", repr(exc))
            out, status = {"output": "", "grade": {}}, "empty"
        except Exception as exc:
            msg = repr(exc)
            kind = "unsupported" if any(w in msg.lower() for w in ("reasoning", "effort", "thinking")) and "400" in msg else "api_error"
            raise Skip(kind, msg[:500])
    app_calls = [c for c in calls if c.get("call")]
    for c in app_calls:
        if model.get("route", "openrouter") == "openrouter" and not _same_model(c["requested_model"], c.get("served_model")):
            raise Skip("served_model_mismatch", f"{c['requested_model']} -> {c.get('served_model')}")
        if model.get("host") and str(c.get("host", "")).lower() != model["host"].lower():
            raise Skip("provider_reroute", f"pinned {model['host']}, served by {c.get('host')}")
    if status == "ok":
        if any(c.get("finish_reason") in ("length", "max_tokens") for c in app_calls):
            status = "truncated"
        elif not str(out.get("output", "")).strip():
            status = "empty"
    j = out.get("judge") or {}
    return {
        "case_id": case["id"], "rep": rep, "suite": suite, "variant": variant_name(model, effort),
        "model": model["slug"], "effort": effort or "default", "group": model.get("group", ""),
        "status": status, "grade_level": case.get("grade"), "tags": case.get("tags", []), "output": out.get("output"),
        "pred": out.get("pred"), "grade": out.get("grade", {}), "topic": out.get("topic"),
        "judge": {k: j.get(k) for k in ("score", "per_criterion", "disagree", "verdicts", "errors")} if j else None,
        "latency_s": round(time.perf_counter() - started, 3),
        "calls": len(app_calls),
        "input_tokens": sum(c.get("input_tokens", 0) for c in app_calls),
        "output_tokens": sum(c.get("output_tokens", 0) for c in app_calls),
        "reasoning_tokens": sum(c.get("reasoning_tokens", 0) for c in app_calls),
        "cost_usd": round(sum((c.get("cost_usd") or 0) for c in app_calls), 6),
        "served_models": sorted({str(c.get("served_model")) for c in app_calls}),
        "hosts": sorted({str(c.get("host")) for c in app_calls}),
        "finish_reasons": sorted({str(c.get("finish_reason")) for c in app_calls}),
        "judge_cost_usd": round(j.get("cost_usd", 0), 6) if j else 0.0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _done(path: Path) -> set:
    if not path.exists():
        return set()
    return {(r["case_id"], r["rep"]) for r in map(json.loads, path.read_text().splitlines()) if r}


async def run_variant(stage, suite, model, effort, cases, reps, ctx, concurrency, timeout_s):
    vdir = RESULTS / stage / suite / variant_name(model, effort)
    vdir.mkdir(parents=True, exist_ok=True)
    results, errors = vdir / "results.jsonl", vdir / "errors.jsonl"
    done = _done(results)
    todo = [(c, r) for r in range(reps) for c in cases if (c["id"], r) not in done]
    if not todo:
        print(f"  {suite:9} {variant_name(model, effort):48} already complete")
        return
    sem, abort = asyncio.Semaphore(concurrency), asyncio.Event()
    counts = {"ok": 0, "fail": 0, "skip": 0}

    async def one(case, rep):
        if abort.is_set():
            return
        async with sem:
            try:
                # a whole homework day is ~35 turns, not one call
                limit_s = timeout_s * (12 if suite == "homework_day" else 1)
                row = await run_case(suite, case, rep, model, effort, ctx, limit_s)
                with results.open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts["ok" if row["status"] == "ok" else "fail"] += 1
            except Skip as s:
                counts["skip"] += 1
                with errors.open("a") as f:
                    f.write(json.dumps({"case_id": case["id"], "rep": rep, "kind": s.kind,
                                        "detail": s.detail, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
                if s.kind == "unsupported":
                    abort.set()  # this effort level isn't accepted; don't burn the whole suite on 400s

    with use_variant(model, effort, "router" if suite == "router" else "reasoner"):
        await asyncio.gather(*(one(c, r) for c, r in todo))
    note = " (effort not supported: variant stopped)" if abort.is_set() else ""
    print(f"  {suite:9} {variant_name(model, effort):48} ok {counts['ok']:3}  failed {counts['fail']:3}  "
          f"harness errors {counts['skip']:3}{note}")


# ── Planning, cost quotes and preflight ──────────────────────────────────────

def plan(args, cfg) -> list[tuple]:
    preset = STAGES[args.stage]
    wanted = set(args.models.split(",")) if args.models else None
    models = [m for m in cfg["model"] if (wanted is None or m["slug"] in wanted)]
    if args.stage == "dry":
        models = [m for m in models if not is_paid(m)]
    if not settings.is_set(settings.typesafe_api_key):
        # Without a key Jev falls back to the LLM router, so its row would be mislabelled.
        models = [m for m in models if m.get("route") != "jev"]
    rows = []
    for suite in (args.suites.split(",") if args.suites else SUITES):
        tier = "router" if suite == "router" else "reasoner"
        efforts = args.efforts.split(",") if args.efforts else preset[f"{tier}_efforts"]
        for m in models:
            if tier not in m["tiers"]:
                continue
            for e in (efforts if is_paid(m) else [""]):
                rows.append((suite, m, e))
    return rows


def _measured_cost() -> dict:
    """Median measured cost per call by (suite, model, effort) and judge cost
    per case by suite, from every results file on disk."""
    per, judges = {}, {}
    for f in RESULTS.glob("*/*/*/results.jsonl"):
        for r in map(json.loads, f.read_text().splitlines()):
            per.setdefault((r["suite"], r["model"], r["effort"]), []).append(r["cost_usd"])
            if r.get("judge_cost_usd"):
                judges.setdefault(r["suite"], []).append(r["judge_cost_usd"])
    return ({k: statistics.median(v) for k, v in per.items()},
            {k: statistics.median(v) for k, v in judges.items()})


def quote(rows, limit, reps, use_judges, grades=None, ids=None) -> tuple[float, int, str]:
    live = prices.cached() or prices.fetch()
    measured, judge_measured = _measured_cost()
    judges = config()["judges"]["models"]
    total, calls, guessed = 0.0, 0, False
    for suite, m, e in rows:
        if not is_paid(m):
            continue
        n = len(select_cases(suite, limit, grades, ids)) * reps
        calls += n
        key = (suite, m["slug"], e or "default")
        if key in measured:
            total += measured[key] * n
        else:
            guessed = True
            p = live.get(m["slug"]) or live.get(m.get("model_id", "")) or {"in": 1.0, "out": 4.0}
            tin, tout = GUESS_TOKENS[suite]
            total += n * (tin * p["in"] + (tout + GUESS_REASONING.get(e, 0)) * p["out"]) / 1e6
        if use_judges and suite in JUDGED:
            if suite in judge_measured:
                total += judge_measured[suite] * n
            else:
                guessed = True
                gin, gout = GUESS_JUDGE_CONV if suite == "conversations" else GUESS_JUDGE
                total += n * sum(gin * live.get(j, {"in": 3})["in"] +
                                 gout * live.get(j, {"out": 15})["out"] for j in judges) / 1e6
    basis = "partly a token GUESS (no measured rows yet for some variants)" if guessed else "measured pilot usage"
    return total, calls, basis


async def preflight(suites, grades=None) -> None:
    """Refuse a paid run when a selected grade has no tutoring notes or topics:
    every reply would be "couldn't find that topic" and every model would
    score the same."""
    from app.db import get_pool

    if not {"tutoring", "practice", "maths", "conversations", "homework_day"} & set(suites):
        return
    wanted = grades or {8, 12}
    pool = await get_pool()
    async with pool.acquire() as conn:
        for g in sorted(wanted):
            chunks = await conn.fetchval("SELECT count(*) FROM caps_chunks WHERE grade = $1", g)
            topics = await conn.fetchval(
                "SELECT count(*) FROM topics t JOIN grades gr ON gr.id = t.grade_id WHERE gr.grade_number = $1", g)
            if not chunks or not topics:
                sys.exit(f"Grade {g} content is missing (caps_chunks={chunks}, topics={topics}). Run:\n"
                         "  docker compose run --rm seed\n"
                         "  docker compose run --rm seed python -m seed.load_curriculum")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--suites", help=f"comma list from {','.join(SUITES)} (default: all)")
    ap.add_argument("--models", help="comma list of slugs from candidates.toml (default: all)")
    ap.add_argument("--efforts", help="comma list overriding the stage's effort levels")
    ap.add_argument("--reps", type=int)
    ap.add_argument("--limit", type=int, help="cases per suite and grade (pilot default 5)")
    ap.add_argument("--grades", help="comma list, e.g. 8,12 (default: every grade in the cases)")
    ap.add_argument("--cases", help="comma list of case ids (overrides --limit)")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--timeout-s", type=float, default=120)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--yes", action="store_true", help="approve spending; without it a paid stage only prints its quote")
    args = ap.parse_args()

    cfg, preset = config(), STAGES[args.stage]
    reps = args.reps or preset["reps"]
    limit = args.limit if args.limit is not None else preset["limit"]
    grades = {int(g) for g in args.grades.split(",")} if args.grades else None
    ids = set(args.cases.split(",")) if args.cases else None
    rows = plan(args, cfg)
    if not rows:
        sys.exit("Nothing to run: check --models / --suites.")
    paid = any(is_paid(m) for _, m, _ in rows)
    use_judges = paid and not args.no_judge
    if use_judges and not settings.is_set(settings.openrouter_api_key):
        print("Judges need OPENROUTER_API_KEY, which isn't set: running without judges.")
        use_judges = False
    variants = len({(m["slug"], e) for _, m, e in rows})
    print(f"Stage {args.stage}: {len(rows)} suite×variant runs over {variants} model×effort variants, "
          f"{reps} repeat(s), {'first ' + str(limit) if limit else 'all'} cases per suite and grade"
          f"{' (grades ' + args.grades + ')' if args.grades else ''}"
          f"{', with judges' if use_judges else ''}.")

    if paid:
        cost, calls, basis = quote(rows, limit, reps, use_judges, grades, ids)
        print(f"Quote: about {calls} model calls, ~${cost:.2f} (basis: {basis}).")
        need = {"openrouter": settings.openrouter_api_key, "groq": settings.groq_api_key,
                "anthropic": settings.anthropic_api_key, "jev": settings.typesafe_api_key}
        missing = sorted({m.get("route", "openrouter") for _, m, _ in rows if is_paid(m)}
                         - {r for r, k in need.items() if settings.is_set(k)})
        if missing:
            sys.exit(f"No API key in .env for: {', '.join(missing)}. Drop those models (--models) or add the key.")
        if not args.yes:
            print("Not run. Re-run with --yes once this spend is approved.")
            return

    suites = sorted({s for s, _, _ in rows})
    await preflight(suites, grades)
    ctx = {"judges": cfg["judges"]["models"] if use_judges else []}
    t0 = time.perf_counter()
    for suite, m, e in rows:
        cases = select_cases(suite, limit, grades, ids)
        await run_variant(args.stage, suite, m, e, cases, reps, ctx, args.concurrency, args.timeout_s)
    spent = sum(r["cost_usd"] + r["judge_cost_usd"]
                for f in (RESULTS / args.stage).glob("*/*/results.jsonl")
                for r in map(json.loads, f.read_text().splitlines()))
    print(f"Done in {time.perf_counter() - t0:.0f}s. Measured spend in stage '{args.stage}' so far: ${spent:.2f}. "
          f"Next: python -m evals.bench.leaderboard --stage {args.stage}")


if __name__ == "__main__":
    asyncio.run(main())
