# Katlego bake-off · stage `dry`

## Recommendation

- **Router:** no candidate passes every gate yet. Most accurate: `stub` (44%).
- **Reasoner:** no candidate passes every gate with a complete set of suites yet.

## Reasoner scorecard

| Model | Effort | Pass | Judge | Maths | Wrong marked right | Tutor p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|---|---|
| stub | default | ❌ | — | 0% | 4% | 0.0 s | $0.0000 | maths, off_grade |

## Router scorecard

| Model | Effort | Pass | Accuracy | p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|
| stub | default | ❌ | 44% | 0.0 s | $0.0000 | accuracy |

## Per-suite detail

Failures (empty, cut off, unparseable) count as wrong. Harness errors are retried on resume and are not scored.

| Suite | Model | Effort | n | failure_rate | accuracy | judge_score | leak_rate | off_grade_pass | false_correct | parsed | answer_correct | judge_errors | state_valid | structured | strategy_follow | judged_right | leak_early | on_problem | tokens_per_turn | p50_s | p95_s | reasoning_tokens | cost_per_call | judge_cost_per_case | harness errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| conversations | stub | default | 8 | 0% | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 56% | 0% | 100% | 0 | 0.2 s | 0.2 s | 0.0 | $0.0000 | $0.0000 | 0 |
| marking | stub | default | 40 | 0% | 38% | — | — | — | 4% | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| maths | stub | default | 40 | 0% | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| practice | stub | default | 20 | 0% | — | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | stub | default | 80 | 0% | 44% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| tutoring | stub | default | 36 | 0% | — | — | 4% | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
