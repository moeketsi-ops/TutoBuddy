"""Turn a stage's results into a scorecard, a recommendation and a showcase.

    python -m evals.bench.leaderboard --stage screen

Writes results/<stage>/leaderboard.md, leaderboard.csv and showcase.md.
Absolute numbers first (seconds, dollars, %), then pass/fail against gates.toml.
"""

import argparse
import csv
import json
import statistics
import tomllib
from pathlib import Path

from evals.bench import graders, prices
from evals.bench.run import HERE, RESULTS, load_cases

SHOWCASE_CASES = 8


def _rows(stage: str) -> list[dict]:
    rows = []
    for f in sorted((RESULTS / stage).glob("*/*/results.jsonl")):
        rows += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return rows


def _errors(stage: str) -> dict:
    out = {}
    for f in (RESULTS / stage).glob("*/*/errors.jsonl"):
        out[(f.parent.parent.name, f.parent.name)] = sum(1 for line in f.read_text().splitlines() if line.strip())
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _p(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))] if xs else None


def _cost(r: dict, live: dict) -> float:
    """Billed cost from the response; falls back to tokens × live price when a
    provider didn't report it."""
    if r.get("cost_usd"):
        return r["cost_usd"]
    # Groq reports no billed cost; estimate from the same model's OpenRouter list price.
    p = live.get(r["model"]) or live.get(r["model"].split(":", 1)[-1])
    if not p or not (r.get("input_tokens") or r.get("output_tokens")):
        return 0.0
    return (r["input_tokens"] * p["in"] + r["output_tokens"] * p["out"]) / 1e6


def suite_metrics(suite: str, rows: list[dict], live: dict) -> dict:
    n = len(rows)
    ok = [r for r in rows if r["status"] == "ok"]
    m = {"n": n, "failure_rate": 1 - len(ok) / n if n else None,
         "p50_s": _p([r["latency_s"] for r in rows], 0.5), "p95_s": _p([r["latency_s"] for r in rows], 0.95),
         "cost_per_call": _mean([_cost(r, live) for r in rows]),
         "judge_cost_per_case": _mean([r.get("judge_cost_usd") or 0 for r in rows]),
         "reasoning_tokens": _mean([r.get("reasoning_tokens") for r in rows])}
    g = lambda r, k: (r.get("grade") or {}).get(k)
    if suite in ("router", "maths"):
        hits = sum(g(r, "correct") or 0 for r in rows)          # failures count as wrong
        m["accuracy"] = hits / n if n else None
        m["accuracy_ci"] = graders.wilson(hits, n)
    if suite == "router":
        for intent in ("homework", "quiz", "smalltalk", "admin"):
            sub = [r for r in rows if r["tags"][0] == intent]
            m[f"recall_{intent}"] = _mean([g(r, "correct") or 0 for r in sub])
    if suite == "tutoring":
        m["leak_rate"] = _mean([g(r, "leaks_answer") for r in ok if "leaks_answer" in (r.get("grade") or {})])
        m["within_120"] = _mean([g(r, "within_120_words") for r in ok])
        m["asks_question"] = _mean([g(r, "asks_question") for r in ok])
        m["link_rate"] = _mean([g(r, "has_link") for r in ok])
        judged = [r for r in ok if (r.get("judge") or {}).get("score") is not None]
        m["judge_score"] = _mean([r["judge"]["score"] for r in judged])
        m["off_grade_pass"] = _mean([r["judge"]["per_criterion"].get("meets_expectation")
                                     for r in judged if r["tags"][0] == "off_grade"])
        m["revision_pass"] = _mean([r["judge"]["per_criterion"].get("meets_expectation")
                                    for r in judged if r["tags"][0] == "revision"])
        m["judge_disagree"] = _mean([float(r["judge"]["disagree"]) for r in judged])
        m["judge_errors"] = _mean([float(bool(r["judge"].get("errors"))) for r in judged])
    if suite == "marking":
        m["accuracy"] = _mean([g(r, "exact") or 0 for r in rows])
        wrong = [r for r in rows if r["tags"][0] != "correct"]
        right = [r for r in rows if r["tags"][0] == "correct"]
        m["false_correct"] = _mean([g(r, "false_correct") or 0 for r in wrong])
        m["false_incorrect"] = _mean([g(r, "false_incorrect") or 0 for r in right])
    if suite == "conversations":
        for k in ("state_valid", "structured", "strategy_follow", "judged_right", "leak_early", "on_problem",
                  "code_checked", "switched_ok", "switch_sequence_ok"):
            m[k] = _mean([g(r, k) for r in ok if g(r, k) is not None])
        turns = [len(str(r.get("output", "")).split("\n\nL: ")) for r in ok]
        tpt = _mean([(r.get("input_tokens", 0) + r.get("output_tokens", 0)) / t
                     for r, t in zip(ok, turns) if t])
        m["tokens_per_turn"] = round(tpt) if tpt is not None else None
    if suite == "homework_day":
        for k in ("solved_share", "turns_per_problem", "switches_per_problem", "judged_right",
                  "code_checked", "leak_early", "seconds_per_reply", "wa_messages", "twilio_usd"):
            m[k] = _mean([g(r, k) for r in ok if g(r, k) is not None])
        m["day_cost_usd"] = _mean([r.get("cost_usd") for r in ok])
        m["calls_per_day"] = _mean([r.get("calls") for r in ok])
    if suite == "practice":
        m["parsed"] = _mean([g(r, "parsed") or 0 for r in rows])
        judged = [r for r in ok if (r.get("judge") or {}).get("score") is not None]
        for k in ("answer_correct", "in_scope", "well_posed"):
            m[k] = _mean([r["judge"]["per_criterion"].get(k) for r in judged])
        m["judge_errors"] = _mean([float(bool(r["judge"].get("errors"))) for r in judged])
    return m


def grade_of(r: dict):
    """Learner grade of a result row (older rows predate the field)."""
    if r.get("grade_level") is not None:
        return r["grade_level"]
    if r["suite"] == "router":
        return None
    return 12 if "grade12" in r.get("tags", []) else 8


# Headline number per suite for the by-grade table.
HEADLINE = {"maths": ("accuracy", "Maths correct"), "tutoring": ("judge_score", "Tutoring judge score"),
            "marking": ("false_correct", "Wrong marked right"), "practice": ("answer_correct", "Practice answer right"),
            "conversations": ("judged_right", "Attempts judged right")}


def by_grade_section(rows: list[dict], live: dict) -> list[str]:
    groups = {}
    for r in rows:
        g = grade_of(r)
        if g is not None and r["suite"] in HEADLINE:
            groups.setdefault((r["model"], r["effort"], r["suite"], g), []).append(r)
    grades = sorted({k[3] for k in groups})
    if len(grades) < 2:
        return []
    variants = sorted({(k[0], k[1]) for k in groups})
    out = ["## By grade\n", "The same models on Grade " + " and Grade ".join(map(str, grades)) +
           " learners. Rates are 0–100%; for *Wrong marked right* lower is better.\n",
           "| Model | Effort | Suite | " + " | ".join(f"Grade {g}" for g in grades) + " |",
           "|---|---|---|" + "---|" * len(grades)]
    for model, effort in variants:
        for suite, (key, label) in HEADLINE.items():
            cells = []
            for g in grades:
                sub_rows = groups.get((model, effort, suite, g))
                v = suite_metrics(suite, sub_rows, live).get(key) if sub_rows else None
                cells.append(_fmt(v) + (f" (n={len(sub_rows)})" if sub_rows else ""))
            if any(c != "—" for c in cells):
                out.append(f"| {model} | {effort} | {label} | " + " | ".join(cells) + " |")
    return out + [""]


def _fmt(v, kind="pct"):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v * 100:.0f}%"
    if kind == "s":
        return f"{v:.1f} s"
    if kind == "usd":
        return f"${v:.4f}" if v < 0.1 else f"${v:.2f}"
    return str(v)


def scorecards(by: dict, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Per model@effort: gate results and cost per 1,000 learner messages."""
    gates, mix = cfg["gates"], cfg["mix"]
    variants = sorted({(model, effort) for (suite, model, effort) in by})
    routers, reasoners = [], []
    for model, effort in variants:
        get = lambda s: by.get((s, model, effort))
        r = get("router")
        if r:
            checks = {"accuracy": r["accuracy"] is not None and r["accuracy"] >= gates["router_accuracy_min"],
                      "p95": r["p95_s"] is not None and r["p95_s"] <= gates["router_p95_max_s"],
                      "format": r["failure_rate"] <= gates["format_failure_max"]}
            routers.append({"model": model, "effort": effort, "accuracy": r["accuracy"], "p95_s": r["p95_s"],
                            "cost_1k": 1000 * (r["cost_per_call"] or 0), "checks": checks, "pass": all(checks.values())})
        mt, mk, tu, pr = get("maths"), get("marking"), get("tutoring"), get("practice")
        if not any((mt, mk, tu, pr)):
            continue
        checks = {
            "maths": mt is not None and mt["accuracy"] >= gates["maths_accuracy_min"],
            "marking": mk is not None and mk["false_correct"] is not None and mk["false_correct"] <= gates["marking_false_correct_max"],
            "leak": tu is not None and tu["leak_rate"] is not None and tu["leak_rate"] <= gates["tutoring_leak_max"],
            "off_grade": tu is not None and tu["off_grade_pass"] is not None and tu["off_grade_pass"] >= gates["off_grade_pass_min"],
            "format": all(s["failure_rate"] <= gates["format_failure_max"] for s in (mt, mk, tu, pr) if s),
            "latency": tu is not None and tu["p95_s"] is not None and tu["p95_s"] <= gates["tutor_p95_max_s"],
        }
        complete = all((tu, pr, mk))
        cost_1k = (mix["tutoring"] * tu["cost_per_call"] + mix["practice"] * pr["cost_per_call"]
                   + mix["marking"] * mk["cost_per_call"]) if complete else None
        reasoners.append({"model": model, "effort": effort, "judge": tu["judge_score"] if tu else None,
                          "maths": mt["accuracy"] if mt else None, "false_correct": mk["false_correct"] if mk else None,
                          "p95_s": tu["p95_s"] if tu else None, "cost_1k": cost_1k, "checks": checks,
                          "pass": all(checks.values()) and complete})
    return routers, reasoners


def recommend(routers, reasoners, cfg, groups) -> list[str]:
    lines, d, mix = [], cfg["decision"], cfg["mix"]
    # The keyword stub is the free floor, never a recommendation (it scored
    # 100% on the 5 easy pilot router cases and was being recommended).
    pr = sorted((r for r in routers if r["pass"] and not str(r["model"]).startswith("stub")),
                key=lambda r: (r["cost_1k"], -(r["accuracy"] or 0)))
    best_router = pr[0] if pr else None
    if best_router:
        lines.append(f"**Router:** `{best_router['model']}` at effort `{best_router['effort']}`: "
                     f"{_fmt(best_router['accuracy'])} accurate, p95 {_fmt(best_router['p95_s'], 's')}, "
                     f"{_fmt(best_router['cost_1k'], 'usd')} per 1,000 messages.")
    else:
        top = max(routers, key=lambda r: r["accuracy"] or 0, default=None)
        lines.append("**Router:** no candidate passes every gate yet." +
                     (f" Most accurate: `{top['model']}` ({_fmt(top['accuracy'])})." if top else ""))
    passers = [r for r in reasoners if r["pass"] and r["judge"] is not None]
    best_tutor = None
    if passers:
        top_judge = max(r["judge"] for r in passers)
        eligible = [r for r in passers if r["judge"] >= top_judge - d["judge_margin"]]
        best_tutor = min(eligible, key=lambda r: r["cost_1k"])
        lines.append(f"**Reasoner:** `{best_tutor['model']}` at effort `{best_tutor['effort']}`: tutoring judge score "
                     f"{_fmt(best_tutor['judge'])} (best passer {_fmt(top_judge)}), maths {_fmt(best_tutor['maths'])}, "
                     f"{_fmt(best_tutor['cost_1k'], 'usd')} per 1,000 messages.")
        open_passers = [r for r in passers if groups.get(r["model"]) == "open"]
        if open_passers and groups.get(best_tutor["model"]) != "open":
            o = min(open_passers, key=lambda r: r["cost_1k"])
            lines.append(f"Best open-weight passer: `{o['model']}` at `{o['effort']}`, judge {_fmt(o['judge'])}, "
                         f"{_fmt(o['cost_1k'], 'usd')} per 1,000 messages.")
    else:
        lines.append("**Reasoner:** no candidate passes every gate with a complete set of suites yet.")
    if best_router and best_tutor:
        per_msg = (best_router["cost_1k"] + best_tutor["cost_1k"]) / 1000
        lines.append(f"**Cost per learner per month:** {_fmt(per_msg * mix['messages_per_learner_month'], 'usd')} "
                     f"at {mix['messages_per_learner_month']} messages a month (model tokens only).")
    # ponytail: per-task split (e.g. cheap marker + strong tutor) not computed yet; add after Stage 3 if costs justify it.
    return lines


def showcase(stage: str, rows: list[dict]) -> str:
    cases = {c["id"]: c for c in load_cases("tutoring")}
    tut = [r for r in rows if r["suite"] == "tutoring" and r["rep"] == 0]
    ids = sorted({r["case_id"] for r in tut})[:SHOWCASE_CASES]
    out = [f"# Showcase: the same learner messages, every model ({stage})\n"]
    for cid in ids:
        c = cases[cid]
        out.append(f"## {cid} · {c['kind']}\n\n**Learner (Grade {c['grade']}):** {c['message']}\n\n_Good reply: {c['expect']}_\n")
        for r in sorted((r for r in tut if r["case_id"] == cid), key=lambda r: r["variant"]):
            reply = (r["output"] or "(no reply)").replace("\n", "\n> ")
            score = (r.get("judge") or {}).get("score")
            out.append(f"**{r['model']} @ {r['effort']}** · {r['latency_s']:.1f} s"
                       f"{' · judge ' + _fmt(score) if score is not None else ''}\n\n> {reply}\n")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    args = ap.parse_args()
    cfg = tomllib.loads((HERE / "gates.toml").read_text())
    groups = {m["slug"]: m.get("group", "") for m in tomllib.loads((HERE / "candidates.toml").read_text())["model"]}
    live = prices.cached()
    rows = _rows(args.stage)
    if not rows:
        raise SystemExit(f"No results under {RESULTS / args.stage}.")
    errors = _errors(args.stage)
    grouped = {}
    for r in rows:
        grouped.setdefault((r["suite"], r["model"], r["effort"]), []).append(r)
    by = {k: suite_metrics(k[0], v, live) for k, v in grouped.items()}
    routers, reasoners = scorecards(by, cfg)

    md = [f"# Katlego bake-off · stage `{args.stage}`\n", "## Recommendation\n",
          *[f"- {line}" for line in recommend(routers, reasoners, cfg, groups)], ""]
    md += ["## Reasoner scorecard\n",
           "| Model | Effort | Pass | Judge | Maths | Wrong marked right | Tutor p95 | $ per 1k msgs | Failed gates |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(reasoners, key=lambda r: (not r["pass"], r["cost_1k"] if r["cost_1k"] is not None else 9e9)):
        failed = ", ".join(k for k, v in r["checks"].items() if not v) or "—"
        md.append(f"| {r['model']} | {r['effort']} | {'✅' if r['pass'] else '❌'} | {_fmt(r['judge'])} | {_fmt(r['maths'])} | "
                  f"{_fmt(r['false_correct'])} | {_fmt(r['p95_s'], 's')} | {_fmt(r['cost_1k'], 'usd')} | {failed} |")
    md += ["", "## Router scorecard\n", "| Model | Effort | Pass | Accuracy | p95 | $ per 1k msgs | Failed gates |",
           "|---|---|---|---|---|---|---|"]
    for r in sorted(routers, key=lambda r: (not r["pass"], r["cost_1k"])):
        failed = ", ".join(k for k, v in r["checks"].items() if not v) or "—"
        md.append(f"| {r['model']} | {r['effort']} | {'✅' if r['pass'] else '❌'} | {_fmt(r['accuracy'])} | "
                  f"{_fmt(r['p95_s'], 's')} | {_fmt(r['cost_1k'], 'usd')} | {failed} |")
    md += [""] + by_grade_section(rows, live)
    md += ["", "## Per-suite detail\n", "Failures (empty, cut off, unparseable) count as wrong. "
           "Harness errors are retried on resume and are not scored.\n"]
    keys = ["n", "failure_rate", "accuracy", "judge_score", "leak_rate", "off_grade_pass", "revision_pass", "false_correct",
            "parsed", "answer_correct", "judge_errors",
            "state_valid", "structured", "strategy_follow", "judged_right", "leak_early", "on_problem", "tokens_per_turn",
            "code_checked", "switched_ok", "switch_sequence_ok",
            "solved_share", "turns_per_problem", "switches_per_problem", "seconds_per_reply",
            "calls_per_day", "day_cost_usd", "wa_messages", "twilio_usd",
            "p50_s", "p95_s", "reasoning_tokens", "cost_per_call", "judge_cost_per_case"]
    md += ["| Suite | Model | Effort | " + " | ".join(keys) + " | harness errors |", "|" + "---|" * (len(keys) + 4)]
    with (RESULTS / args.stage / "leaderboard.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["suite", "model", "effort", *keys, "harness_errors"])
        for (suite, model, effort), m in sorted(by.items()):
            err = errors.get((suite, f"{model.replace(':', '_').replace('/', '__')}@{effort}"), 0)
            w.writerow([suite, model, effort, *[m.get(k) for k in keys], err])
            cells = [_fmt(m.get(k), "s" if k.endswith("_s") or k == "seconds_per_reply" else "usd" if "cost" in k or k.endswith("_usd") else "raw" if k in ("n", "reasoning_tokens", "tokens_per_turn", "turns_per_problem",
                                     "switches_per_problem", "calls_per_day", "wa_messages") else "pct")
                     for k in keys]
            md.append(f"| {suite} | {model} | {effort} | " + " | ".join(cells) + f" | {err} |")
    (RESULTS / args.stage / "leaderboard.md").write_text("\n".join(md) + "\n")
    (RESULTS / args.stage / "showcase.md").write_text(showcase(args.stage, rows))
    spent = sum(r["cost_usd"] + (r.get("judge_cost_usd") or 0) for r in rows)
    print("\n".join(recommend(routers, reasoners, cfg, groups)))
    print(f"\n{len(rows)} rows · measured spend ${spent:.2f} · wrote {RESULTS / args.stage}/leaderboard.md, "
          f"leaderboard.csv, showcase.md")


if __name__ == "__main__":
    main()
