# Katlego bake-off · stage `pilot`

## Recommendation

- **Router:** `groq:openai/gpt-oss-20b` at effort `none`: 100% accurate, p95 0.9 s, $0.0045 per 1,000 messages.
- **Reasoner:** no candidate passes every gate with a complete set of suites yet.

## Reasoner scorecard

| Model | Effort | Pass | Judge | Maths | Wrong marked right | Tutor p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|---|---|
| groq:openai/gpt-oss-120b | low | ❌ | — | 100% | — | 1.0 s | $0.0398 | marking, off_grade |
| groq:qwen/qwen3.8-27b | low | ❌ | — | 100% | — | 14.5 s | $0.57 | marking, off_grade, format, latency |

## Router scorecard

| Model | Effort | Pass | Accuracy | p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|
| groq:openai/gpt-oss-20b | none | ✅ | 100% | 0.9 s | $0.0045 | — |
| groq:openai/gpt-oss-120b | none | ✅ | 100% | 0.8 s | $0.0101 | — |
| groq:qwen/qwen3.8-27b | none | ✅ | 100% | 0.7 s | $0.0105 | — |

## By grade

The same models on Grade 8 and Grade 12 learners. Rates are 0–100%; for *Wrong marked right* lower is better.

| Model | Effort | Suite | Grade 8 | Grade 12 |
|---|---|---|---|---|
| groq:openai/gpt-oss-120b | low | Maths correct | 100% (n=3) | 100% (n=3) |
| groq:openai/gpt-oss-120b | low | Tutoring judge score | — (n=3) | — (n=3) |
| groq:openai/gpt-oss-120b | low | Wrong marked right | — (n=3) | — (n=3) |
| groq:openai/gpt-oss-120b | low | Practice answer right | — (n=3) | — (n=3) |
| groq:openai/gpt-oss-120b | low | Attempts judged right | 78% (n=3) | 78% (n=3) |
| groq:qwen/qwen3.8-27b | low | Maths correct | 100% (n=3) | 100% (n=3) |
| groq:qwen/qwen3.8-27b | low | Tutoring judge score | — (n=3) | — (n=3) |
| groq:qwen/qwen3.8-27b | low | Wrong marked right | — (n=3) | — (n=3) |
| groq:qwen/qwen3.8-27b | low | Practice answer right | — (n=3) | — (n=3) |
| groq:qwen/qwen3.8-27b | none | Attempts judged right | 67% (n=3) | 44% (n=3) |


## Per-suite detail

Failures (empty, cut off, unparseable) count as wrong. Harness errors are retried on resume and are not scored.

| Suite | Model | Effort | n | failure_rate | accuracy | judge_score | leak_rate | off_grade_pass | revision_pass | false_correct | parsed | answer_correct | judge_errors | state_valid | structured | strategy_follow | judged_right | leak_early | on_problem | tokens_per_turn | p50_s | p95_s | reasoning_tokens | cost_per_call | judge_cost_per_case | harness errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| conversations | groq:openai/gpt-oss-120b | low | 6 | 0% | — | — | — | — | — | — | — | — | — | 100% | 88% | 100% | 78% | 0% | 83% | 1788 | 54.4 s | 77.0 s | 376.1666666666667 | $0.0004 | $0.0000 | 5 |
| conversations | groq:qwen/qwen3.8-27b | none | 6 | 0% | — | — | — | — | — | — | — | — | — | 92% | 92% | 96% | 56% | 0% | 100% | 1421 | 46.9 s | 53.1 s | 0.0 | $0.0013 | $0.0000 | 0 |
| marking | groq:openai/gpt-oss-120b | low | 6 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.6 s | 0.9 s | 34.5 | $0.0000 | $0.0000 | 0 |
| marking | groq:qwen/qwen3.8-27b | low | 6 | 0% | 83% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 5.8 s | 16.3 s | 110.66666666666667 | $0.0004 | $0.0000 | 2 |
| maths | groq:openai/gpt-oss-120b | low | 6 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.2 s | 1.4 s | 24.166666666666668 | $0.0001 | $0.0000 | 0 |
| maths | groq:qwen/qwen3.8-27b | low | 6 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.8 s | 0.9 s | 139.5 | $0.0006 | $0.0000 | 0 |
| practice | groq:openai/gpt-oss-120b | low | 6 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 0.7 s | 1.1 s | 56.166666666666664 | $0.0001 | $0.0000 | 0 |
| practice | groq:qwen/qwen3.8-27b | low | 6 | 17% | — | — | — | — | — | — | 83% | — | — | — | — | — | — | — | — | — | 21.2 s | 29.6 s | 563.1666666666666 | $0.0015 | $0.0000 | 2 |
| router | groq:openai/gpt-oss-120b | none | 3 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.4 s | 0.8 s | 16.333333333333332 | $0.0000 | $0.0000 | 0 |
| router | groq:openai/gpt-oss-20b | none | 3 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.4 s | 0.9 s | 9.333333333333334 | $0.0000 | $0.0000 | 0 |
| router | groq:qwen/qwen3.8-27b | none | 3 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.4 s | 0.7 s | 0.0 | $0.0000 | $0.0000 | 0 |
| tutoring | groq:openai/gpt-oss-120b | low | 6 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.8 s | 1.0 s | 28.833333333333332 | $0.0001 | $0.0000 | 0 |
| tutoring | groq:qwen/qwen3.8-27b | low | 6 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 14.3 s | 14.5 s | 150.16666666666666 | $0.0006 | $0.0000 | 2 |
