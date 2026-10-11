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
SUITES = ("router", "maths", "tutoring", "marking", "practice")
JUDGED = ("tutoring", "practice")

# Stage presets; every value can be overridden on the command line.
STAGES = {
    "dry":     {"limit": None, "reps": 1, "router_efforts": [""],                         "reasoner_efforts": [""]},
    "pilot":   {"limit": 5,    "reps": 1, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
    "screen":  {"limit": None, "reps": 1, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
    "sweep":   {"limit": None, "reps": 3, "router_efforts": ["none", "minimal", "low"],   "reasoner_efforts": ["none", "low", "medium", "high"]},
    "confirm": {"limit": None, "reps": 3, "router_efforts": ["none"],                     "reasoner_efforts": ["low"]},
}

# Rough tokens per call, used ONLY to quote the pilot before any measurement
# exists. Every later quote comes from measured pilot rows.
GUESS_TOKENS = {"router": (350, 5), "maths": (1400, 500), "tutoring": (1800, 250),
                "marking": (700, 80), "practice": (2200, 150)}
GUESS_REASONING = {"": 0, "none": 0, "minimal": 300, "low": 800, "medium": 2000, "high": 4000}
GUESS_JUDGE = (1200, 900)  # per judge call


def load_cases(suite: str) -> list[dict]:
    lines = (HERE / "cases" / f"{suite}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def config() -> dict:
    return tomllib.loads((HERE / "candidates.toml").read_text())


def variant_name(model: dict, effort: str) -> str:
    return f"{model['slug'].replace('/', '__')}@{effort or 'default'}"


def is_paid(model: dict) -> bool:
    return model.get("route", "openrouter") != "stub"


_FIELDS = ("llm_provider", "reasoner_provider", "router_provider", "openrouter_router_model",
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


RUNNERS = {"router": _router, "maths": _maths, "tutoring": _tutoring, "marking": _marking, "practice": _practice}


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
        "status": status, "tags": case.get("tags", []), "output": out.get("output"),
        "pred": out.get("pred"), "grade": out.get("grade", {}),
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
                row = await run_case(suite, case, rep, model, effort, ctx, timeout_s)
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


def quote(rows, limit, reps, use_judges) -> tuple[float, int, str]:
    live = prices.cached() or prices.fetch()
    measured, judge_measured = _measured_cost()
    judges = config()["judges"]["models"]
    total, calls, guessed = 0.0, 0, False
    for suite, m, e in rows:
        if not is_paid(m):
            continue
        n = min(limit or 10**9, len(load_cases(suite))) * reps
        calls += n
        key = (suite, m["slug"], e or "default")
        if key in measured:
            total += measured[key] * n
        else:
            guessed = True
            p = live.get(m["slug"], {"in": 1.0, "out": 4.0})
            tin, tout = GUESS_TOKENS[suite]
            total += n * (tin * p["in"] + (tout + GUESS_REASONING.get(e, 0)) * p["out"]) / 1e6
        if use_judges and suite in JUDGED:
            if suite in judge_measured:
                total += judge_measured[suite] * n
            else:
                guessed = True
                total += n * sum(GUESS_JUDGE[0] * live.get(j, {"in": 3})["in"] +
                                 GUESS_JUDGE[1] * live.get(j, {"out": 15})["out"] for j in judges) / 1e6
    basis = "partly a token GUESS (no measured rows yet for some variants)" if guessed else "measured pilot usage"
    return total, calls, basis


async def preflight(suites) -> None:
    from app.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        chunks = await conn.fetchval("SELECT count(*) FROM caps_chunks WHERE grade = 8")
        topics = await conn.fetchval(
            "SELECT count(*) FROM topics t JOIN grades g ON g.id = t.grade_id WHERE g.grade_number = 8")
    if {"tutoring", "practice", "maths"} & set(suites) and (not chunks or not topics):
        sys.exit("Grade 8 content is missing (caps_chunks=%s, topics=%s). Every reply would be "
                 "\"couldn't find that topic\" and every model would score the same. Run:\n"
                 "  docker compose run --rm seed\n"
                 "  docker compose run --rm seed python -m seed.load_curriculum" % (chunks, topics))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--suites", help=f"comma list from {','.join(SUITES)} (default: all)")
    ap.add_argument("--models", help="comma list of slugs from candidates.toml (default: all)")
    ap.add_argument("--efforts", help="comma list overriding the stage's effort levels")
    ap.add_argument("--reps", type=int)
    ap.add_argument("--limit", type=int, help="cases per suite (pilot default 5)")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--timeout-s", type=float, default=120)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--yes", action="store_true", help="approve spending; without it a paid stage only prints its quote")
    args = ap.parse_args()

    cfg, preset = config(), STAGES[args.stage]
    reps = args.reps or preset["reps"]
    limit = args.limit if args.limit is not None else preset["limit"]
    rows = plan(args, cfg)
    if not rows:
        sys.exit("Nothing to run: check --models / --suites.")
    paid = any(is_paid(m) for _, m, _ in rows)
    use_judges = paid and not args.no_judge
    variants = len({(m["slug"], e) for _, m, e in rows})
    print(f"Stage {args.stage}: {len(rows)} suite×variant runs over {variants} model×effort variants, "
          f"{reps} repeat(s), {'first ' + str(limit) if limit else 'all'} cases per suite"
          f"{', with judges' if use_judges else ''}.")

    if paid:
        cost, calls, basis = quote(rows, limit, reps, use_judges)
        print(f"Quote: about {calls} model calls, ~${cost:.2f} (basis: {basis}).")
        if not settings.is_set(settings.openrouter_api_key):
            sys.exit("OPENROUTER_API_KEY is not set in .env, so no paid stage can run yet.")
        if not args.yes:
            print("Not run. Re-run with --yes once this spend is approved.")
            return

    suites = sorted({s for s, _, _ in rows})
    await preflight(suites)
    ctx = {"judges": cfg["judges"]["models"] if use_judges else []}
    t0 = time.perf_counter()
    for suite, m, e in rows:
        cases = load_cases(suite)[:limit] if limit else load_cases(suite)
        await run_variant(args.stage, suite, m, e, cases, reps, ctx, args.concurrency, args.timeout_s)
    spent = sum(r["cost_usd"] + r["judge_cost_usd"]
                for f in (RESULTS / args.stage).glob("*/*/results.jsonl")
                for r in map(json.loads, f.read_text().splitlines()))
    print(f"Done in {time.perf_counter() - t0:.0f}s. Measured spend in stage '{args.stage}' so far: ${spent:.2f}. "
          f"Next: python -m evals.bench.leaderboard --stage {args.stage}")


if __name__ == "__main__":
    asyncio.run(main())
