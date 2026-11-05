"""What a learner costs per month in model calls, from MEASURED bench rows.
Free: reads result files only.

    python -m evals.bench.cost_model --stage judged
    python -m evals.bench.cost_model --stage judged --fx 17.5 --messages 120

Per learner message, Katlego makes: one router call (every message), then
a tutoring turn, a practice question, a marked answer or a past-paper
answer marked against the memo, in the shares set in gates.toml [mix].
Each call's cost is the median billed cost from the bench:

  tutoring turn   conversations suite: billed cost / learner turns (this
                  includes the memory prompt and any leak-guard rewrite)
  practice        practice suite, per question
  marking         marking suite, per answer
  paper marking   NOT measured yet: estimated as 1.5 x a marking call
                  (the memo points make the prompt longer). Marked "est".
  router          router suite (for the router model you name)

For any suite missing in --stage, rows from other stages are used and the
table says which stage each number came from. Judge spend is excluded: it
is a cost of testing, not of serving learners. Hosting, WhatsApp and
speech-to-text are not model calls and are not in this number.
"""

import argparse
import json
import statistics
import tomllib
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"
PAPER_MARK_FACTOR = 1.5


def _turns() -> dict[str, int]:
    out = {}
    for line in (HERE / "cases" / "conversations.jsonl").read_text().splitlines():
        if line.strip():
            c = json.loads(line)
            out[c["id"]] = len(c["turns"])
    return out


def _rows(stage: str, suite: str, slug: str) -> list[dict]:
    rows = []
    for f in (RESULTS / stage / suite).glob("*/results.jsonl"):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r["model"] == slug and r["status"] == "ok" and r.get("cost_usd"):
                    rows.append(r)
    return rows


def per_call(stage: str, suite: str, slug: str) -> tuple[float | None, str | None]:
    """(median $ per call, stage it came from)."""
    stages = [stage] + sorted(p.name for p in RESULTS.iterdir() if p.is_dir() and p.name != stage)
    turns = _turns()
    for st in stages:
        rows = _rows(st, suite, slug)
        if not rows:
            continue
        if suite == "conversations":
            vals = [r["cost_usd"] / turns[r["case_id"]] for r in rows if r["case_id"] in turns]
        else:
            vals = [r["cost_usd"] / max(1, r.get("calls") or 1) for r in rows]
        if vals:
            return statistics.median(vals), st
    return None, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--models", help="comma list of tutor models (default: every model with conversation rows)")
    ap.add_argument("--router", default="z-ai/glm-5.3-flash", help="router model slug")
    ap.add_argument("--messages", type=int, help="messages per learner per month (default: gates.toml)")
    ap.add_argument("--fx", type=float, help="rand per US dollar, to show ZAR too")
    args = ap.parse_args()

    mix = tomllib.loads((HERE / "gates.toml").read_text())["mix"]
    msgs = args.messages or mix["messages_per_learner_month"]
    paper_share = mix.get("paper_marking", 0)
    if args.models:
        models = args.models.split(",")
    else:
        models = sorted({json.loads(l)["model"] for f in (RESULTS / args.stage / "conversations").glob("*/results.jsonl")
                         for l in f.read_text().splitlines() if l.strip()})
    router, rsrc = per_call(args.stage, "router", args.router)
    print(f"Mix per 1,000 messages: tutoring {mix['tutoring']}, practice {mix['practice']}, marking "
          f"{mix['marking']}, paper marking {paper_share}; router on every message "
          f"({args.router}: {'$%.6f' % router if router is not None else 'not measured'}"
          f"{' from ' + rsrc if rsrc else ''}). {msgs} messages per learner per month.\n")
    head = "| Tutor model | $ per tutoring turn | $ per practice Q | $ per marked answer | $ per paper answer (est) | $ per 1,000 messages | $ per learner per month |"
    if args.fx:
        head += " R per learner per month |"
    print(head)
    print("|" + "---|" * (head.count("|") - 1))
    for slug in models:
        tu, tsrc = per_call(args.stage, "conversations", slug)
        pr, psrc = per_call(args.stage, "practice", slug)
        mk, msrc = per_call(args.stage, "marking", slug)
        if tu is None:
            continue
        missing = [n for n, v in (("practice", pr), ("marking", mk)) if v is None]
        pr_v, mk_v = pr or 0.0, mk or 0.0
        paper = mk_v * PAPER_MARK_FACTOR
        per_1k = (mix["tutoring"] * tu + mix["practice"] * pr_v + mix["marking"] * mk_v
                  + paper_share * paper + 1000 * (router or 0.0))
        month = per_1k / 1000 * msgs
        src = {s for s in (tsrc, psrc, msrc) if s and s != args.stage}
        line = (f"| {slug} | ${tu:.5f} | {'$%.5f' % pr if pr is not None else '—'} | "
                f"{'$%.5f' % mk if mk is not None else '—'} | ${paper:.5f} | ${per_1k:.3f} | ${month:.4f}"
                + (f" (missing: {', '.join(missing)})" if missing else "")
                + (f" (some rows from {', '.join(sorted(src))})" if src else "") + " |")
        if args.fx:
            line += f" R{month * args.fx:.2f} |"
        print(line)


if __name__ == "__main__":
    main()
