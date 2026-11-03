# Katlego bake-off · stage `dry`

## Recommendation

- **Router:** no candidate passes every gate yet. Most accurate: `stub` (44%).
- **Reasoner:** no candidate passes every gate with a complete set of suites yet.

## Reasoner scorecard

| Model | Effort | Pass | Judge | Maths | Wrong marked right | Tutor p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|---|---|
| stub | default | ❌ | — | 0% | 3% | 0.0 s | $0.0000 | maths, off_grade |

## Router scorecard

| Model | Effort | Pass | Accuracy | p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|
| stub | default | ❌ | 44% | 0.0 s | $0.0000 | accuracy |

## By grade

The same models on Grade 8 and Grade 12 learners. Rates are 0–100%; for *Wrong marked right* lower is better.

| Model | Effort | Suite | Grade 8 | Grade 12 |
|---|---|---|---|---|
| stub | default | Maths correct | 0% (n=40) | 0% (n=31) |
| stub | default | Tutoring judge score | — (n=36) | — (n=24) |
| stub | default | Wrong marked right | 4% (n=40) | 0% (n=20) |
| stub | default | Practice answer right | — (n=20) | — (n=12) |
| stub | default | Attempts judged right | 96% (n=12) | 92% (n=4) |


## Per-suite detail

Failures (empty, cut off, unparseable) count as wrong. Harness errors are retried on resume and are not scored.

| Suite | Model | Effort | n | failure_rate | accuracy | judge_score | leak_rate | off_grade_pass | revision_pass | false_correct | parsed | answer_correct | judge_errors | state_valid | structured | strategy_follow | judged_right | leak_early | on_problem | tokens_per_turn | code_checked | switched_ok | switch_sequence_ok | solved_share | turns_per_problem | switches_per_problem | seconds_per_reply | calls_per_day | day_cost_usd | wa_messages | twilio_usd | p50_s | p95_s | reasoning_tokens | cost_per_call | judge_cost_per_case | harness errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| conversations | stub | default | 16 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 95% | 0% | 100% | 0 | 86% | 100% | 100% | — | — | — | — | — | — | — | — | 0.2 s | 0.9 s | 0.0 | $0.0000 | $0.0000 | 0 |
| homework_day | stub | default | 2 | 0% | — | — | — | — | — | — | — | — | — | — | — | — | 95% | 0% | — | — | 90% | — | — | 29% | 3.925 | 0.215 | 0.0 s | 0.0 | $0.0000 | 55.0 | $0.28 | 0.4 s | 0.4 s | 0.0 | $0.0000 | $0.0000 | 0 |
| marking | stub | default | 60 | 0% | 37% | — | — | — | — | 3% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| maths | stub | default | 71 | 0% | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| practice | stub | default | 32 | 0% | — | — | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | stub | default | 80 | 0% | 44% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| tutoring | stub | default | 60 | 0% | — | — | 2% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
