"""Export every bake-off case to CASES.md for founder sign-off (no spend).

    python -m evals.bench.cases
"""

from evals.bench.run import HERE, load_cases


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ⏎ ")


def main() -> None:
    out = ["# Bake-off test cases (for sign-off)\n",
           "Every case the benchmark sends to the models, grouped by suite. Mark anything that's wrong, "
           "unrealistic or missing. Paid stages only run after you both approve this file.\n"]
    spec = {
        "router": (["id", "text", "intent"], "Learner messages and the label the router should give."),
        "maths": (["id", "topic", "question", "answer"], "Grade 8 questions with the hand-verified final answer."),
        "tutoring": (["id", "kind", "message", "expect"], "Learner messages to a Grade 8 profile, and what a good reply does."),
        "marking": (["id", "question", "model_answer", "learner_answer", "expected"], "Learner answers and the verdict the marker should give."),
        "practice": (["id", "topic", "band"], "Topic and mastery level the tutor must write a practice question for."),
    }
    for suite, (cols, blurb) in spec.items():
        rows = load_cases(suite)
        out += [f"## {suite.title()} ({len(rows)} cases)\n", blurb + "\n",
                "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(_cell(r.get(c) if r.get(c) is not None else "—") for c in cols) + " |" for r in rows]
        out.append("")
    (HERE / "CASES.md").write_text("\n".join(out))
    print(f"Wrote {HERE / 'CASES.md'}")


if __name__ == "__main__":
    main()
