# Katlego bake-off · stage `pilot`

## Recommendation

- **Router:** `stub` at effort `default`: 100% accurate, p95 0.0 s, $0.0000 per 1,000 messages.
- **Reasoner:** no candidate passes every gate with a complete set of suites yet.

## Reasoner scorecard

| Model | Effort | Pass | Judge | Maths | Wrong marked right | Tutor p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|---|---|
| stub | default | ❌ | — | 0% | 0% | 0.0 s | $0.0000 | maths, off_grade |
| groq:openai/gpt-oss-120b | low | ❌ | — | 89% | 8% | 1.0 s | $0.0382 | maths, marking, off_grade |
| z-ai/glm-5.3-flash | low | ❌ | — | 94% | 0% | 4.8 s | $0.0527 | off_grade |
| openai/gpt-6-luna | low | ❌ | — | 100% | 0% | 3.8 s | $0.11 | off_grade |
| openai/gpt-oss-120b | low | ❌ | — | 94% | 8% | 0.9 s | $0.14 | marking, off_grade |
| anthropic/claude-haiku-5.5 | low | ❌ | — | 100% | 8% | 4.0 s | $0.19 | marking, off_grade |
| deepseek/deepseek-v4-flash | low | ❌ | — | 100% | 8% | 15.0 s | $0.22 | marking, off_grade, format, latency |
| qwen/qwen3.8-27b | low | ❌ | — | 94% | 0% | 4.5 s | $0.56 | off_grade, format |
| groq:qwen/qwen3.8-27b | low | ❌ | — | 94% | 0% | 14.5 s | $0.59 | off_grade, format, latency |
| openai/gpt-5.4-mini | low | ❌ | — | 94% | 8% | 2.7 s | $0.92 | marking, off_grade |
| qwen/qwen3.6-35b-a3b | low | ❌ | — | 83% | 0% | 26.2 s | $1.11 | maths, off_grade, format, latency |
| deepseek/deepseek-v4-pro | low | ❌ | — | 94% | 8% | 11.0 s | $1.37 | marking, off_grade, format, latency |
| qwen/qwen3.5-35b-a3b | low | ❌ | — | 61% | 0% | 16.8 s | $1.77 | maths, off_grade, format, latency |
| moonshotai/kimi-k3 | low | ❌ | — | 100% | 0% | 4.3 s | $1.78 | leak, off_grade |
| x-ai/grok-4.3 | low | ❌ | — | 94% | 0% | 7.3 s | $1.82 | off_grade |
| anthropic/claude-sonnet-5.5 | low | ❌ | — | 100% | 0% | 4.3 s | $3.36 | off_grade |
| x-ai/grok-4.7 | low | ❌ | — | 100% | 0% | 9.6 s | $3.66 | off_grade |

## Router scorecard

| Model | Effort | Pass | Accuracy | p95 | $ per 1k msgs | Failed gates |
|---|---|---|---|---|---|---|
| stub | default | ✅ | 100% | 0.0 s | $0.0000 | — |
| groq:openai/gpt-oss-20b | none | ✅ | 100% | 0.9 s | $0.0048 | — |
| groq:openai/gpt-oss-120b | none | ✅ | 100% | 0.8 s | $0.0100 | — |
| groq:qwen/qwen3.8-27b | none | ✅ | 100% | 0.7 s | $0.0105 | — |
| qwen/qwen3.6-35b-a3b | none | ✅ | 100% | 1.1 s | $0.0118 | — |
| openai/gpt-5.4-nano | none | ✅ | 100% | 1.2 s | $0.0242 | — |
| openai/gpt-oss-120b | low | ✅ | 100% | 0.5 s | $0.0302 | — |
| x-ai/grok-4.3 | none | ✅ | 100% | 1.0 s | $0.20 | — |
| deepseek/deepseek-v4-flash | none | ❌ | 100% | 1.6 s | $0.0066 | p95 |
| z-ai/glm-5.3-flash | low | ❌ | 100% | 2.0 s | $0.0088 | p95 |
| meta-llama/llama-4-scout | none | ❌ | 100% | 1.5 s | $0.0114 | p95 |
| anthropic/claude-haiku-5.5 | none | ❌ | 100% | 1.7 s | $0.0138 | p95 |
| openai/gpt-oss-20b | low | ❌ | 100% | 2.4 s | $0.0144 | p95 |
| qwen/qwen3.5-35b-a3b | none | ❌ | 100% | 3.0 s | $0.0174 | p95 |
| qwen/qwen3.8-27b | none | ❌ | 100% | 1.6 s | $0.0214 | p95 |
| openai/gpt-5.4-mini | none | ❌ | 100% | 1.8 s | $0.0900 | p95 |

## By grade

The same models on Grade 8 and Grade 12 learners. Rates are 0–100%; for *Wrong marked right* lower is better.

| Model | Effort | Suite | Grade 8 | Grade 12 |
|---|---|---|---|---|
| anthropic/claude-haiku-5.5 | low | Maths correct | 100% (n=9) | 100% (n=9) |
| anthropic/claude-haiku-5.5 | low | Tutoring judge score | — (n=9) | — (n=9) |
| anthropic/claude-haiku-5.5 | low | Wrong marked right | 14% (n=12) | 0% (n=10) |
| anthropic/claude-haiku-5.5 | low | Practice answer right | — (n=7) | — (n=5) |
| anthropic/claude-haiku-5.5 | low | Attempts judged right | 81% (n=6) | 89% (n=3) |
| anthropic/claude-sonnet-5.5 | low | Maths correct | 100% (n=9) | 100% (n=9) |
| anthropic/claude-sonnet-5.5 | low | Tutoring judge score | — (n=9) | — (n=9) |
| anthropic/claude-sonnet-5.5 | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| anthropic/claude-sonnet-5.5 | low | Practice answer right | — (n=7) | — (n=5) |
| anthropic/claude-sonnet-5.5 | low | Attempts judged right | 89% (n=6) | 100% (n=3) |
| deepseek/deepseek-v4-flash | low | Maths correct | 100% (n=9) | 100% (n=9) |
| deepseek/deepseek-v4-flash | low | Tutoring judge score | — (n=9) | — (n=9) |
| deepseek/deepseek-v4-flash | low | Wrong marked right | 14% (n=12) | 0% (n=10) |
| deepseek/deepseek-v4-flash | low | Practice answer right | — (n=7) | — (n=5) |
| deepseek/deepseek-v4-flash | low | Attempts judged right | 80% (n=6) | 83% (n=3) |
| deepseek/deepseek-v4-pro | low | Maths correct | 100% (n=9) | 89% (n=9) |
| deepseek/deepseek-v4-pro | low | Tutoring judge score | — (n=9) | — (n=9) |
| deepseek/deepseek-v4-pro | low | Wrong marked right | 14% (n=12) | 0% (n=10) |
| deepseek/deepseek-v4-pro | low | Practice answer right | — (n=7) | — (n=5) |
| deepseek/deepseek-v4-pro | low | Attempts judged right | 83% (n=6) | 67% (n=3) |
| groq:openai/gpt-oss-120b | low | Maths correct | 100% (n=9) | 78% (n=9) |
| groq:openai/gpt-oss-120b | low | Tutoring judge score | — (n=9) | — (n=9) |
| groq:openai/gpt-oss-120b | low | Wrong marked right | 14% (n=12) | 0% (n=10) |
| groq:openai/gpt-oss-120b | low | Practice answer right | — (n=7) | — (n=5) |
| groq:openai/gpt-oss-120b | low | Attempts judged right | 70% (n=5) | 78% (n=3) |
| groq:qwen/qwen3.8-27b | low | Maths correct | 100% (n=9) | 86% (n=7) |
| groq:qwen/qwen3.8-27b | low | Tutoring judge score | — (n=9) | — (n=8) |
| groq:qwen/qwen3.8-27b | low | Wrong marked right | 0% (n=12) | 0% (n=9) |
| groq:qwen/qwen3.8-27b | low | Practice answer right | — (n=7) | — (n=5) |
| groq:qwen/qwen3.8-27b | none | Attempts judged right | 67% (n=3) | 44% (n=3) |
| moonshotai/kimi-k3 | low | Maths correct | 100% (n=9) | 100% (n=9) |
| moonshotai/kimi-k3 | low | Tutoring judge score | — (n=9) | — (n=9) |
| moonshotai/kimi-k3 | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| moonshotai/kimi-k3 | low | Practice answer right | — (n=7) | — (n=5) |
| moonshotai/kimi-k3 | low | Attempts judged right | 100% (n=6) | 100% (n=3) |
| openai/gpt-5.4-mini | low | Maths correct | 100% (n=9) | 89% (n=9) |
| openai/gpt-5.4-mini | low | Tutoring judge score | — (n=9) | — (n=9) |
| openai/gpt-5.4-mini | low | Wrong marked right | 14% (n=12) | 0% (n=10) |
| openai/gpt-5.4-mini | low | Practice answer right | — (n=7) | — (n=5) |
| openai/gpt-5.4-mini | low | Attempts judged right | 81% (n=6) | 89% (n=3) |
| openai/gpt-6-luna | low | Maths correct | 100% (n=9) | 100% (n=9) |
| openai/gpt-6-luna | low | Tutoring judge score | — (n=9) | — (n=9) |
| openai/gpt-6-luna | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| openai/gpt-6-luna | low | Practice answer right | — (n=7) | — (n=5) |
| openai/gpt-6-luna | low | Attempts judged right | 75% (n=6) | 100% (n=3) |
| openai/gpt-oss-120b | low | Maths correct | 100% (n=9) | 89% (n=9) |
| openai/gpt-oss-120b | low | Tutoring judge score | — (n=9) | — (n=9) |
| openai/gpt-oss-120b | low | Wrong marked right | 14% (n=12) | 0% (n=10) |
| openai/gpt-oss-120b | low | Practice answer right | — (n=7) | — (n=5) |
| openai/gpt-oss-120b | low | Attempts judged right | 83% (n=6) | 100% (n=3) |
| qwen/qwen3.5-35b-a3b | low | Maths correct | 67% (n=9) | 56% (n=9) |
| qwen/qwen3.5-35b-a3b | low | Tutoring judge score | — (n=9) | — (n=9) |
| qwen/qwen3.5-35b-a3b | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| qwen/qwen3.5-35b-a3b | low | Practice answer right | — (n=7) | — (n=5) |
| qwen/qwen3.5-35b-a3b | low | Attempts judged right | 100% (n=6) | 83% (n=3) |
| qwen/qwen3.6-35b-a3b | low | Maths correct | 78% (n=9) | 89% (n=9) |
| qwen/qwen3.6-35b-a3b | low | Tutoring judge score | — (n=9) | — (n=9) |
| qwen/qwen3.6-35b-a3b | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| qwen/qwen3.6-35b-a3b | low | Practice answer right | — (n=7) | — (n=5) |
| qwen/qwen3.6-35b-a3b | low | Attempts judged right | — (n=6) | — (n=3) |
| qwen/qwen3.8-27b | low | Maths correct | 100% (n=9) | 89% (n=9) |
| qwen/qwen3.8-27b | low | Tutoring judge score | — (n=9) | — (n=9) |
| qwen/qwen3.8-27b | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| qwen/qwen3.8-27b | low | Practice answer right | — (n=7) | — (n=5) |
| qwen/qwen3.8-27b | low | Attempts judged right | 100% (n=6) | 100% (n=3) |
| stub | default | Maths correct | 0% (n=9) | 0% (n=9) |
| stub | default | Tutoring judge score | — (n=9) | — (n=9) |
| stub | default | Wrong marked right | 0% (n=12) | 0% (n=10) |
| stub | default | Practice answer right | — (n=7) | — (n=5) |
| stub | default | Attempts judged right | 64% (n=6) | 56% (n=3) |
| x-ai/grok-4.3 | low | Maths correct | 100% (n=8) | 89% (n=9) |
| x-ai/grok-4.3 | low | Tutoring judge score | — (n=9) | — (n=9) |
| x-ai/grok-4.3 | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| x-ai/grok-4.3 | low | Practice answer right | — (n=7) | — (n=5) |
| x-ai/grok-4.3 | low | Attempts judged right | 89% (n=6) | 100% (n=3) |
| x-ai/grok-4.7 | low | Maths correct | 100% (n=9) | 100% (n=9) |
| x-ai/grok-4.7 | low | Tutoring judge score | — (n=9) | — (n=9) |
| x-ai/grok-4.7 | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| x-ai/grok-4.7 | low | Practice answer right | — (n=7) | — (n=5) |
| x-ai/grok-4.7 | low | Attempts judged right | 81% (n=6) | 89% (n=3) |
| z-ai/glm-5.3-flash | low | Maths correct | 100% (n=9) | 89% (n=9) |
| z-ai/glm-5.3-flash | low | Tutoring judge score | — (n=9) | — (n=9) |
| z-ai/glm-5.3-flash | low | Wrong marked right | 0% (n=12) | 0% (n=10) |
| z-ai/glm-5.3-flash | low | Practice answer right | — (n=7) | — (n=5) |
| z-ai/glm-5.3-flash | low | Attempts judged right | 89% (n=6) | 78% (n=3) |


## Per-suite detail

Failures (empty, cut off, unparseable) count as wrong. Harness errors are retried on resume and are not scored.

| Suite | Model | Effort | n | failure_rate | accuracy | judge_score | leak_rate | off_grade_pass | revision_pass | false_correct | parsed | answer_correct | judge_errors | state_valid | structured | strategy_follow | judged_right | leak_early | on_problem | tokens_per_turn | p50_s | p95_s | reasoning_tokens | cost_per_call | judge_cost_per_case | harness errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| conversations | anthropic/claude-haiku-5.5 | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 83% | 11% | 100% | 3273 | 14.3 s | 19.5 s | 748.3333333333334 | $0.0019 | $0.0000 | 0 |
| conversations | anthropic/claude-sonnet-5.5 | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 93% | 0% | 100% | 3112 | 12.6 s | 16.2 s | 136.88888888888889 | $0.0320 | $0.0000 | 0 |
| conversations | deepseek/deepseek-v4-flash | low | 9 | 22% | — | — | — | — | — | — | — | — | — | 96% | 96% | 86% | 81% | 0% | 86% | 2427 | 49.4 s | 70.5 s | 2599.8888888888887 | $0.0006 | $0.0000 | 1 |
| conversations | deepseek/deepseek-v4-pro | low | 9 | 44% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 80% | 0% | 100% | 2216 | 65.7 s | 91.2 s | 3047.8888888888887 | $0.0109 | $0.0000 | 0 |
| conversations | groq:openai/gpt-oss-120b | low | 8 | 0% | — | — | — | — | — | — | — | — | — | 100% | 86% | 100% | 73% | 0% | 75% | 1785 | 46.9 s | 77.0 s | 391.375 | $0.0004 | $0.0000 | 7 |
| conversations | groq:qwen/qwen3.8-27b | none | 6 | 0% | — | — | — | — | — | — | — | — | — | 92% | 92% | 96% | 56% | 0% | 100% | 1421 | 46.9 s | 53.1 s | 0.0 | $0.0013 | $0.0000 | 0 |
| conversations | moonshotai/kimi-k3 | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 97% | 100% | 0% | 100% | 1909 | 13.1 s | 27.3 s | 326.77777777777777 | $0.0121 | $0.0000 | 0 |
| conversations | openai/gpt-5.4-mini | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 83% | 11% | 100% | 1772 | 12.2 s | 15.0 s | 633.7777777777778 | $0.0091 | $0.0000 | 0 |
| conversations | openai/gpt-6-luna | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 83% | 0% | 67% | 1730 | 14.7 s | 16.0 s | 599.3333333333334 | $0.0012 | $0.0000 | 0 |
| conversations | openai/gpt-oss-120b | low | 9 | 33% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 89% | 0% | 67% | 1818 | 4.3 s | 5.1 s | 342.77777777777777 | $0.0011 | $0.0000 | 0 |
| conversations | qwen/qwen3.5-35b-a3b | low | 9 | 56% | — | — | — | — | — | — | — | — | — | 88% | 100% | 100% | 92% | 0% | 75% | 3231 | 21.9 s | 68.4 s | 3996.1111111111113 | $0.0058 | $0.0000 | 0 |
| conversations | qwen/qwen3.6-35b-a3b | low | 9 | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 21.6 s | 29.0 s | 1417.5555555555557 | $0.0015 | $0.0000 | 0 |
| conversations | qwen/qwen3.8-27b | low | 9 | 22% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 100% | 0% | 100% | 1866 | 19.6 s | 54.7 s | 1544.3333333333333 | $0.0048 | $0.0000 | 0 |
| conversations | stub | default | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 61% | 0% | 100% | 0 | 0.0 s | 0.1 s | 0.0 | $0.0000 | $0.0000 | 0 |
| conversations | x-ai/grok-4.3 | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 93% | 0% | 100% | 2580 | 45.7 s | 62.5 s | 3025.1111111111113 | $0.0160 | $0.0000 | 0 |
| conversations | x-ai/grok-4.7 | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 100% | 83% | 0% | 89% | 3722 | 44.0 s | 57.4 s | 2871.1111111111113 | $0.0356 | $0.0000 | 0 |
| conversations | z-ai/glm-5.3-flash | low | 9 | 0% | — | — | — | — | — | — | — | — | — | 100% | 100% | 97% | 85% | 0% | 89% | 1550 | 10.6 s | 11.8 s | 575.8888888888889 | $0.0007 | $0.0000 | 0 |
| marking | anthropic/claude-haiku-5.5 | low | 22 | 0% | 91% | — | — | — | — | 8% | — | — | — | — | — | — | — | — | — | — | 1.3 s | 4.3 s | 47.0 | $0.0001 | $0.0000 | 0 |
| marking | anthropic/claude-sonnet-5.5 | low | 22 | 0% | 100% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 1.7 s | 2.7 s | 0.0 | $0.0020 | $0.0000 | 0 |
| marking | deepseek/deepseek-v4-flash | low | 22 | 5% | 82% | — | — | — | — | 8% | — | — | — | — | — | — | — | — | — | — | 5.2 s | 18.1 s | 397.27272727272725 | $0.0002 | $0.0000 | 0 |
| marking | deepseek/deepseek-v4-pro | low | 22 | 5% | 82% | — | — | — | — | 8% | — | — | — | — | — | — | — | — | — | — | 6.1 s | 20.0 s | 310.59090909090907 | $0.0011 | $0.0000 | 0 |
| marking | groq:openai/gpt-oss-120b | low | 22 | 0% | 91% | — | — | — | — | 8% | — | — | — | — | — | — | — | — | — | — | 0.7 s | 0.9 s | 29.59090909090909 | $0.0000 | $0.0000 | 0 |
| marking | groq:qwen/qwen3.8-27b | low | 21 | 0% | 90% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 1.2 s | 30.2 s | 180.95238095238096 | $0.0005 | $0.0000 | 3 |
| marking | moonshotai/kimi-k3 | low | 22 | 0% | 95% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 2.1 s | 4.8 s | 45.31818181818182 | $0.0014 | $0.0000 | 0 |
| marking | openai/gpt-5.4-mini | low | 22 | 0% | 86% | — | — | — | — | 8% | — | — | — | — | — | — | — | — | — | — | 1.9 s | 2.4 s | 28.863636363636363 | $0.0006 | $0.0000 | 0 |
| marking | openai/gpt-6-luna | low | 22 | 0% | 100% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 2.7 s | 3.3 s | 40.04545454545455 | $0.0001 | $0.0000 | 0 |
| marking | openai/gpt-oss-120b | low | 22 | 0% | 91% | — | — | — | — | 8% | — | — | — | — | — | — | — | — | — | — | 0.5 s | 0.8 s | 33.27272727272727 | $0.0001 | $0.0000 | 0 |
| marking | qwen/qwen3.5-35b-a3b | low | 22 | 45% | 50% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 14.0 s | 28.1 s | 2260.2727272727275 | $0.0029 | $0.0000 | 0 |
| marking | qwen/qwen3.6-35b-a3b | low | 22 | 91% | 32% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 9.8 s | 17.2 s | 1200.9545454545455 | $0.0012 | $0.0000 | 0 |
| marking | qwen/qwen3.8-27b | low | 22 | 0% | 86% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 2.8 s | 4.4 s | 197.22727272727272 | $0.0005 | $0.0000 | 0 |
| marking | stub | default | 22 | 0% | 36% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 0.0 s | 1.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| marking | x-ai/grok-4.3 | low | 22 | 0% | 95% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 7.3 s | 10.0 s | 453.40909090909093 | $0.0017 | $0.0000 | 0 |
| marking | x-ai/grok-4.7 | low | 22 | 0% | 91% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 5.4 s | 6.4 s | 289.72727272727275 | $0.0034 | $0.0000 | 0 |
| marking | z-ai/glm-5.3-flash | low | 22 | 0% | 100% | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | — | 2.1 s | 3.1 s | 88.72727272727273 | $0.0000 | $0.0000 | 0 |
| maths | anthropic/claude-haiku-5.5 | low | 18 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.0 s | 2.7 s | 0.0 | $0.0002 | $0.0000 | 0 |
| maths | anthropic/claude-sonnet-5.5 | low | 18 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.7 s | 2.1 s | 0.0 | $0.0024 | $0.0000 | 0 |
| maths | deepseek/deepseek-v4-flash | low | 18 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 3.8 s | 12.5 s | 162.11111111111111 | $0.0001 | $0.0000 | 0 |
| maths | deepseek/deepseek-v4-pro | low | 18 | 6% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 5.0 s | 7.8 s | 245.61111111111111 | $0.0012 | $0.0000 | 0 |
| maths | groq:openai/gpt-oss-120b | low | 18 | 0% | 89% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.9 s | 1.3 s | 37.05555555555556 | $0.0001 | $0.0000 | 0 |
| maths | groq:qwen/qwen3.8-27b | low | 16 | 0% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.9 s | 1.4 s | 184.75 | $0.0006 | $0.0000 | 2 |
| maths | moonshotai/kimi-k3 | low | 18 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.3 s | 3.5 s | 32.22222222222222 | $0.0019 | $0.0000 | 0 |
| maths | openai/gpt-5.4-mini | low | 18 | 0% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.9 s | 3.3 s | 18.11111111111111 | $0.0009 | $0.0000 | 0 |
| maths | openai/gpt-6-luna | low | 18 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.6 s | 3.5 s | 49.72222222222222 | $0.0001 | $0.0000 | 0 |
| maths | openai/gpt-oss-120b | low | 18 | 0% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.2 s | 1.4 s | 35.0 | $0.0002 | $0.0000 | 0 |
| maths | qwen/qwen3.5-35b-a3b | low | 18 | 33% | 61% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 9.9 s | 22.5 s | 1556.5 | $0.0019 | $0.0000 | 0 |
| maths | qwen/qwen3.6-35b-a3b | low | 18 | 17% | 83% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 10.7 s | 26.3 s | 1284.7777777777778 | $0.0013 | $0.0000 | 0 |
| maths | qwen/qwen3.8-27b | low | 18 | 0% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.3 s | 6.2 s | 206.83333333333334 | $0.0007 | $0.0000 | 0 |
| maths | stub | default | 18 | 0% | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| maths | x-ai/grok-4.3 | low | 17 | 0% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 6.5 s | 10.1 s | 324.94117647058823 | $0.0016 | $0.0000 | 1 |
| maths | x-ai/grok-4.7 | low | 18 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 3.9 s | 6.5 s | 302.05555555555554 | $0.0037 | $0.0000 | 0 |
| maths | z-ai/glm-5.3-flash | low | 18 | 0% | 94% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.7 s | 3.4 s | 111.88888888888889 | $0.0000 | $0.0000 | 0 |
| practice | anthropic/claude-haiku-5.5 | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 4.0 s | 5.2 s | 255.5 | $0.0003 | $0.0000 | 0 |
| practice | anthropic/claude-sonnet-5.5 | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 2.1 s | 2.7 s | 0.0 | $0.0041 | $0.0000 | 0 |
| practice | deepseek/deepseek-v4-flash | low | 12 | 50% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 11.8 s | 17.1 s | 909.1666666666666 | $0.0004 | $0.0000 | 0 |
| practice | deepseek/deepseek-v4-pro | low | 12 | 8% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 13.8 s | 45.8 s | 787.3333333333334 | $0.0031 | $0.0000 | 0 |
| practice | groq:openai/gpt-oss-120b | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 0.7 s | 1.0 s | 39.833333333333336 | $0.0000 | $0.0000 | 0 |
| practice | groq:qwen/qwen3.8-27b | low | 12 | 8% | — | — | — | — | — | — | 92% | — | — | — | — | — | — | — | — | — | 3.3 s | 22.5 s | 564.0833333333334 | $0.0015 | $0.0000 | 2 |
| practice | moonshotai/kimi-k3 | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 3.3 s | 4.8 s | 125.83333333333333 | $0.0025 | $0.0000 | 0 |
| practice | openai/gpt-5.4-mini | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 3.2 s | 3.8 s | 157.0 | $0.0015 | $0.0000 | 0 |
| practice | openai/gpt-6-luna | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 3.2 s | 6.3 s | 150.5 | $0.0002 | $0.0000 | 0 |
| practice | openai/gpt-oss-120b | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 0.7 s | 1.1 s | 27.666666666666668 | $0.0002 | $0.0000 | 0 |
| practice | qwen/qwen3.5-35b-a3b | low | 12 | 75% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 14.8 s | 25.4 s | 2023.4166666666667 | $0.0024 | $0.0000 | 0 |
| practice | qwen/qwen3.6-35b-a3b | low | 12 | 100% | — | — | — | — | — | — | 92% | — | — | — | — | — | — | — | — | — | 26.8 s | 31.5 s | 1498.5 | $0.0017 | $0.0000 | 0 |
| practice | qwen/qwen3.8-27b | low | 12 | 8% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 5.8 s | 20.2 s | 515.6666666666666 | $0.0011 | $0.0000 | 0 |
| practice | stub | default | 12 | 0% | — | — | — | — | — | — | 0% | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| practice | x-ai/grok-4.3 | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 7.1 s | 11.5 s | 700.0833333333334 | $0.0029 | $0.0000 | 0 |
| practice | x-ai/grok-4.7 | low | 12 | 0% | — | — | — | — | — | — | 100% | — | — | — | — | — | — | — | — | — | 8.2 s | 16.5 s | 624.9166666666666 | $0.0064 | $0.0000 | 0 |
| practice | z-ai/glm-5.3-flash | low | 12 | 0% | — | — | — | — | — | — | 83% | — | — | — | — | — | — | — | — | — | 2.7 s | 3.6 s | 133.08333333333334 | $0.0001 | $0.0000 | 0 |
| router | anthropic/claude-haiku-5.5 | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.0 s | 1.7 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | deepseek/deepseek-v4-flash | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.4 s | 1.6 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | groq:openai/gpt-oss-120b | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.4 s | 0.8 s | 15.6 | $0.0000 | $0.0000 | 0 |
| router | groq:openai/gpt-oss-20b | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.6 s | 0.9 s | 13.0 | $0.0000 | $0.0000 | 0 |
| router | groq:qwen/qwen3.8-27b | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.4 s | 0.7 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | meta-llama/llama-4-scout | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.4 s | 1.5 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | openai/gpt-5.4-mini | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.1 s | 1.8 s | 0.0 | $0.0001 | $0.0000 | 0 |
| router | openai/gpt-5.4-nano | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.9 s | 1.2 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | openai/gpt-oss-120b | low | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.3 s | 0.5 s | 12.8 | $0.0000 | $0.0000 | 0 |
| router | openai/gpt-oss-20b | low | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.6 s | 2.4 s | 10.2 | $0.0000 | $0.0000 | 0 |
| router | qwen/qwen3.5-35b-a3b | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.2 s | 3.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | qwen/qwen3.6-35b-a3b | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.7 s | 1.1 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | qwen/qwen3.8-27b | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.0 s | 1.6 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | stub | default | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| router | x-ai/grok-4.3 | none | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.9 s | 1.0 s | 0.0 | $0.0002 | $0.0000 | 0 |
| router | z-ai/glm-5.3-flash | low | 5 | 0% | 100% | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.7 s | 2.0 s | 85.6 | $0.0000 | $0.0000 | 0 |
| tutoring | anthropic/claude-haiku-5.5 | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.8 s | 4.0 s | 76.88888888888889 | $0.0002 | $0.0000 | 0 |
| tutoring | anthropic/claude-sonnet-5.5 | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.5 s | 4.3 s | 22.555555555555557 | $0.0044 | $0.0000 | 0 |
| tutoring | deepseek/deepseek-v4-flash | low | 18 | 17% | — | — | 7% | — | — | — | — | — | — | — | — | — | — | — | — | — | 6.4 s | 15.0 s | 420.44444444444446 | $0.0002 | $0.0000 | 0 |
| tutoring | deepseek/deepseek-v4-pro | low | 18 | 0% | — | — | 6% | — | — | — | — | — | — | — | — | — | — | — | — | — | 6.8 s | 11.0 s | 231.61111111111111 | $0.0014 | $0.0000 | 0 |
| tutoring | groq:openai/gpt-oss-120b | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.7 s | 1.0 s | 19.72222222222222 | $0.0000 | $0.0000 | 0 |
| tutoring | groq:qwen/qwen3.8-27b | low | 17 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 1.4 s | 14.5 s | 147.52941176470588 | $0.0006 | $0.0000 | 3 |
| tutoring | moonshotai/kimi-k3 | low | 18 | 0% | — | — | 12% | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.6 s | 4.3 s | 41.44444444444444 | $0.0022 | $0.0000 | 0 |
| tutoring | openai/gpt-5.4-mini | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.2 s | 2.7 s | 31.055555555555557 | $0.0011 | $0.0000 | 0 |
| tutoring | openai/gpt-6-luna | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 2.6 s | 3.8 s | 46.166666666666664 | $0.0001 | $0.0000 | 0 |
| tutoring | openai/gpt-oss-120b | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.5 s | 0.9 s | 17.166666666666668 | $0.0002 | $0.0000 | 0 |
| tutoring | qwen/qwen3.5-35b-a3b | low | 18 | 56% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 9.1 s | 16.8 s | 1490.7222222222222 | $0.0019 | $0.0000 | 0 |
| tutoring | qwen/qwen3.6-35b-a3b | low | 18 | 28% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 16.2 s | 26.2 s | 1131.4444444444443 | $0.0013 | $0.0000 | 0 |
| tutoring | qwen/qwen3.8-27b | low | 18 | 0% | — | — | 6% | — | — | — | — | — | — | — | — | — | — | — | — | — | 3.0 s | 4.5 s | 148.55555555555554 | $0.0006 | $0.0000 | 0 |
| tutoring | stub | default | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 0.0 s | 0.0 s | 0.0 | $0.0000 | $0.0000 | 0 |
| tutoring | x-ai/grok-4.3 | low | 18 | 0% | — | — | 6% | — | — | — | — | — | — | — | — | — | — | — | — | — | 5.0 s | 7.3 s | 345.3333333333333 | $0.0021 | $0.0000 | 0 |
| tutoring | x-ai/grok-4.7 | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 4.3 s | 9.6 s | 212.83333333333334 | $0.0041 | $0.0000 | 0 |
| tutoring | z-ai/glm-5.3-flash | low | 18 | 0% | — | — | 0% | — | — | — | — | — | — | — | — | — | — | — | — | — | 3.1 s | 4.8 s | 177.44444444444446 | $0.0001 | $0.0000 | 0 |
