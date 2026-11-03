"""Per-model summary of the conversations suite for one stage, for the
before/after comparison after the 31 Oct bake-off fixes. Free: reads
result files only.

    python -m evals.bench.recheck_summary --stage recheck
    python -m evals.bench.recheck_summary --stage recheck --cases c01-c11   # same cases as 31 Oct
"""

import argparse
import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

# The topic each scripted conversation is about (where mastery evidence belongs).
EXPECTED_TOPIC = {
    "c01": "Algebraic Equations", "c02": "Algebraic Equations", "c03": "Algebraic Equations",
    "c04": "Integers", "c05": "Common Fractions", "c06": "Exponents",
    "c07": "Algebraic Expressions", "c08": "Area and Perimeter", "c09": "Differential calculus",
    "c10": "Exponential and logarithmic functions", "c11": "Patterns, sequences and series",
    "c12": "Algebraic Equations", "c13": "Algebraic Equations", "c14": "Algebraic Equations",
    "c15": "Exponential and logarithmic functions", "c16": "Algebraic Equations",
}


def _ids(spec: str | None) -> set[str] | None:
    if not spec:
        return None
    out = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out |= {f"c{i:02d}" for i in range(int(a[1:]), int(b[1:]) + 1)}
        else:
            out.add(part)
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarise(stage: str, cases: set[str] | None) -> list[dict]:
    rows = []
    for f in sorted((RESULTS / stage / "conversations").glob("*/results.jsonl")):
        recs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        recs = [r for r in recs if cases is None or r["case_id"] in cases]
        if not recs:
            continue
        ok = [r for r in recs if r["status"] == "ok"]
        turns = sum(r.get("calls") or 0 for r in ok) or 1
        g = lambda k: _mean([r["grade"].get(k) for r in ok])  # noqa: E731
        topics = [r.get("topic") == EXPECTED_TOPIC.get(r["case_id"]) for r in ok if "topic" in r]
        rows.append({
            "variant": f.parent.name, "convs": len(recs), "failed": len(recs) - len(ok),
            "on_problem": g("on_problem"), "label_right": g("judged_right"),
            "leak_early": g("leak_early"), "code_checked": g("code_checked"),
            "guard_rewrote": g("guard_rewrote"), "guard_masked": g("guard_masked"),
            "topic_right": _mean(topics) if topics else None,
            "cost_per_turn": sum(r["cost_usd"] for r in ok) / turns,
            "in_tokens_per_call": sum(r.get("input_tokens") or 0 for r in ok) / turns,
            "s_per_turn": statistics.median([r["latency_s"] / max(1, r.get("calls") or 1) for r in ok])
            if ok else None,
        })
    return rows


def _pct(x):
    return "—" if x is None else f"{100 * x:.0f}%"


def _s(x):
    return "—" if x is None else f"{x:.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--cases", help="e.g. c01-c11 or c04,c09")
    args = ap.parse_args()
    rows = summarise(args.stage, _ids(args.cases))
    print("| Model | Convs | Failed | Stayed on problem | Label right | Answer too early | "
          "Code checked | Guard rewrote / masked | Mastery topic right | $ per turn | Input tokens per call | s per turn |")
    print("|" + "---|" * 12)
    for r in rows:
        print(f"| {r['variant']} | {r['convs']} | {r['failed']} | {_pct(r['on_problem'])} | "
              f"{_pct(r['label_right'])} | {_pct(r['leak_early'])} | {_pct(r['code_checked'])} | "
              f"{_pct(r['guard_rewrote'])} / {_pct(r['guard_masked'])} | {_pct(r['topic_right'])} | "
              f"${r['cost_per_turn']:.5f} | {r['in_tokens_per_call']:.0f} | "
              f"{_s(r['s_per_turn'])} |")


if __name__ == "__main__":
    main()
