"""Re-apply the automatic graders to stored replies (no model calls, no cost).

    python -m evals.bench.regrade --stage pilot

Use after a grader fix: maths answers and tutoring checks are recomputed from
each row's saved output; judge scores and timings are left untouched.
"""

import argparse
import json

from evals.bench import graders
from evals.bench.run import RESULTS, load_cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    stage = ap.parse_args().stage
    cases = {s: {c["id"]: c for c in load_cases(s)} for s in ("maths", "tutoring")}
    changed = 0
    for suite in ("maths", "tutoring"):
        for f in (RESULTS / stage / suite).glob("*/results.jsonl"):
            rows = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
            for r in rows:
                c, out, before = cases[suite][r["case_id"]], r.get("output") or "", dict(r["grade"])
                if suite == "maths":
                    r["grade"]["correct"] = float(graders.answer_matches(out, c["answers"]))
                elif r["status"] == "ok":
                    r["grade"].update(within_120_words=float(graders.word_count(out) <= 120),
                                      asks_question=float(graders.asks_question(out)),
                                      has_link=float(graders.has_link(out)))
                    if c["answers"]:
                        r["grade"]["leaks_answer"] = float(graders.leaks_answer(out, c["answers"]))
                changed += r["grade"] != before
            f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"Regraded stage {stage}: {changed} rows changed.")


if __name__ == "__main__":
    main()
