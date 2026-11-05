# Learner journeys (real WhatsApp path)

These run a simulated learner's phone against the real gateway and worker,
the same path a WhatsApp message takes. They need the app running
(`docker compose up -d`) and, for real tutoring, a real model in `.env`.

## 0. Point the app at a real model (once)

In `.env` (Notepad or VS Code):

```
LLM_PROVIDER=openrouter
OPENROUTER_ROUTER_MODEL=z-ai/glm-5.3-flash
OPENROUTER_REASONER_MODEL=z-ai/glm-5.3-flash     # or openai/gpt-6-luna
OPENROUTER_VISION_MODEL=openai/gpt-6-luna
```

Then `docker compose up -d --force-recreate gateway worker`. Check with
`Get-Content .env | Select-String LLM_PROVIDER`. Put it back to `stub` after.

All commands below share this prefix (PowerShell, from `Documents\TutoBuddy-cto`):

```
docker compose run --rm -e GATEWAY_URL=http://gateway:8000 -e MOCKWA_URL=http://mockwa:8001 evals python -m ...
```

## 1. Full journey: does every part run?

`evals.journey.full`: 40 steps from consent to end-line check-in, with a
sibling on Grade 10 for past papers and squads. Each step is PASS, FAIL or
WARN (WARN = the code ran, a model-dependent expectation wasn't met). About
60 messages; a few cents on GLM-5.3 Flash.

## 2. Homework week: pedagogy and mastery over seven days

`evals.journey.week --learner scripted` then `--learner ai`.
Grade 8, Area and Perimeter then Surface Area and Volume, as the 2026 ATP has
for Term 4 weeks 5-7. Day 0 check-in (baseline), seven days of homework
(`homework_week_g8.json`), day 8 check-in (end-line). Between days the
learner's clock moves on a day. About 70-90 learner messages; cents.

The AI learner is `openai/gpt-5.4-nano` playing a learner whose
misconceptions fade after solving a problem type twice. Change it with
`--learner-model`.

## 3. Per-learner usage

`app.reports.usage --days 7 --fx 16.02 --csv evals/bench/results/journey/usage.csv`

Tokens, cost, calls by type, by day and per learner, with a short "what to
look at" list. Works on the pilot database the same way.

Results land in `evals\bench\results\journey\` on your machine (that folder is shared with the container).
