"""Human spot-check of the AI judges (no spend).

    python -m evals.bench.human_review export --stage confirm   # writes review/sheet.md + sheet.csv
    python -m evals.bench.human_review score  --stage confirm   # after you fill sheet.csv

Exports 20 blinded tutoring replies (no model names). Each founder marks each
criterion Y or N in sheet.csv; `score` reports how often the judges agree.
"""

import argparse
import csv
import json
import random

from evals.bench.judge import TUTORING_CRITERIA
from evals.bench.leaderboard import _rows
from evals.bench.run import RESULTS, load_cases

SAMPLE = 20


def export(stage: str) -> None:
    rows = [r for r in _rows(stage) if r["suite"] == "tutoring" and (r.get("judge") or {}).get("score") is not None]
    if not rows:
        raise SystemExit(f"No judged tutoring rows in stage {stage}.")
    rng = random.Random(7)
    rng.shuffle(rows)
    # Spread the sample across models and case kinds first, then fill up at random.
    picked, seen = [], set()
    for r in rows:
        if (r["model"], r["tags"][0]) not in seen:
            seen.add((r["model"], r["tags"][0]))
            picked.append(r)
    picked = picked[:SAMPLE] + [r for r in rows if r not in picked][:max(0, SAMPLE - len(picked))]
    cases = {c["id"]: c for c in load_cases("tutoring")}
    out_dir = RESULTS / stage / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = ["# Judge spot-check\n", "Mark each criterion Y or N in `sheet.csv`, one row per reply. "
             "Model names are hidden on purpose.\n", "Criteria:\n",
             *[f"- **{k}**: {v.format(grade=8, expect='the expectation shown for that reply')}" for k, v in TUTORING_CRITERIA.items()], ""]
    key = {}
    for i, r in enumerate(picked, 1):
        bid, c = f"R{i:02d}", cases[r["case_id"]]
        key[bid] = {"case_id": r["case_id"], "model": r["model"], "effort": r["effort"],
                    "judge": r["judge"]["per_criterion"]}
        reply = (r["output"] or "").replace("\n", "\n> ")
        sheet += [f"## {bid}\n", f"**Learner:** {c['message']}\n", f"_Expectation: {c['expect']}_\n", f"> {reply}\n"]
    (out_dir / "sheet.md").write_text("\n".join(sheet))
    (out_dir / "key.json").write_text(json.dumps(key, indent=1))
    with (out_dir / "sheet.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["reply", *TUTORING_CRITERIA, "comment"])
        for bid in key:
            w.writerow([bid, *[""] * len(TUTORING_CRITERIA), ""])
    print(f"Wrote {out_dir}/sheet.md and sheet.csv ({len(key)} replies).")


def score(stage: str) -> None:
    out_dir = RESULTS / stage / "review"
    key = json.loads((out_dir / "key.json").read_text())
    agree = {k: [] for k in TUTORING_CRITERIA}
    with (out_dir / "sheet.csv").open() as f:
        for row in csv.DictReader(f):
            for k in TUTORING_CRITERIA:
                human = row.get(k, "").strip().upper()[:1]
                if human in ("Y", "N"):
                    judged = key[row["reply"]]["judge"].get(k, 0) >= 0.5
                    agree[k].append((human == "Y") == judged)
    total = [a for v in agree.values() for a in v]
    for k, v in agree.items():
        print(f"{k:20} {sum(v)}/{len(v)} agree" if v else f"{k:20} not marked")
    if total:
        rate = sum(total) / len(total)
        print(f"\nOverall judge–human agreement: {rate:.0%} "
              f"({'meets' if rate >= 0.8 else 'BELOW'} the 80% bar in the plan)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["export", "score"])
    ap.add_argument("--stage", required=True)
    a = ap.parse_args()
    (export if a.action == "export" else score)(a.stage)
