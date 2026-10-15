# Katlego model bake-off

Benchmarks candidate models and reasoning-effort levels on the **real Katlego code paths**: the same prompts, CAPS retrieval and parsing the bot uses. The output is a scorecard and a recommendation for the router model, the reasoner model, their effort levels, and the cost per learner per month.

Every model call goes through OpenRouter with one key (`OPENROUTER_API_KEY` in `.env`). **Paid stages print a cost quote and stop unless you pass `--yes`.**

## Files

| File | What it is |
|---|---|
| `candidates.toml` | Models under test, their tiers, and the two judges. Edit freely |
| `gates.toml` | Pass/fail gates, decision rule, and the message mix used for cost |
| `cases/*.jsonl` | 216 Grade 8 cases: router 80, maths 40, tutoring 36, marking 40, practice 20; plus 8 multi-turn `conversations` (memory, STATE line, strategy choice; see `docs/memory-pedagogy.md`) |
| `CASES.md` | All cases in one readable file for sign-off (`python -m evals.bench.cases`) |
| `run.py` | Runs the suites. Resumable; one row per case per repeat |
| `graders.py` / `judge.py` | Automatic checks, and the two blind AI judges |
| `leaderboard.py` | Scorecard, recommendation and side-by-side showcase |
| `human_review.py` | The 20-reply human spot-check of the judges |
| `results/<stage>/…` | Output: `results.jsonl`, `errors.jsonl`, `leaderboard.md`, `showcase.md` |

## Stages

Run everything inside the evals container; it sees the seeded database and mounts this folder, so case edits need no rebuild.

```bash
alias bench='docker compose run --rm evals python -m'
bench evals.bench.prices                      # free: checks slugs, prints live prices
bench evals.bench.cases                       # free: writes CASES.md for sign-off
bench evals.bench.run --stage dry             # free: stub floor, proves the pipeline
bench evals.bench.leaderboard --stage dry

bench evals.bench.judge --sanity              # paid, cents: bad replies must fail
bench evals.bench.run --stage pilot           # prints the quote and stops
bench evals.bench.run --stage pilot --yes     # paid: 5 cases per suite, every model
bench evals.bench.leaderboard --stage pilot
```

Later stages follow the plan: `screen` runs first with `--suites router,maths,marking` (automatic grading only), then `--suites tutoring,practice` on the models that passed. After that come `sweep` and `confirm`. Narrow any run with `--models a,b`, `--efforts low,medium`, `--suites …`, `--reps N` or `--limit N`. A rerun resumes where it stopped. `--no-judge` skips the judges.

## How a model gets switched

For each model@effort variant, the runner points the app's own settings at that model (`LLM_PROVIDER=openrouter`, the model slugs, and `ROUTER_EFFORT` or `REASONER_EFFORT`). Variants run one at a time. Production behaviour is unchanged when those settings are blank. The same settings carry the winner into production.

## What protects the comparison

- **Database preflight.** A paid stage refuses to run if the Grade 8 notes or topics are missing.
- **Model and host checks.** A reply from a different model than requested, or from an unpinned host, is logged to `errors.jsonl` and never scored.
- **Failures count as wrong.** A reply that is empty, cut off by the token limit, or unparseable is a failure for the model.
- **Unsupported efforts stop early.** If a provider rejects an effort level, that variant stops after the first rejection instead of failing every case.
- **Cost is the billed amount.** It's OpenRouter's `usage.cost` on each response, and judge spend is kept in its own column.
