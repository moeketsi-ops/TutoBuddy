# CPA + TMU switching (20 Oct 2026)

Spec: "Katlego CPA + mastery switching spec v0.1" (claude.ai doc, 20 Oct
2026). Source for strands and methods: DBE "Mathematics Teaching and
Learning Framework for South Africa: Teaching Mathematics for Understanding"
(draft 6), pages as printed.

## What changed

| Piece | File | What it does |
|---|---|---|
| Code-side answer checking | `app/tutor/answer_check.py` | SymPy judges attempts at one-variable equations BEFORE the model call: correct, step_forward (equivalent equation, or one root of several) or wrong. Words and explanations are left to the model. Learner text only reaches the parser if it is digits, operators and whitelisted names. |
| CPA levels | `app/tutor/representation.py` | concrete / pictorial / abstract instructions per phase (Grade 8-9 vs 10-12), WhatsApp emoji rules, start level from mastery or the learner's own level stats, the bridge-to-symbols step |
| TMU strands + methods | `app/tutor/tmu.py`, `seed/tmu/methods.json` | the four strands, strand tag per piece of evidence, 11 topic entries of alternative methods and common errors (8 from the DBE framework with pages, 3 marked "Katlego team (to review)") |
| Switching rule | `pedagogy.plan_switch` | 3 learner turns with no progress -> switch, max 2 per problem: first one CPA level toward concrete (same strategy), then a strategy change, then a worked example on a SIMILAR problem. "Show me another way" switches at once. 10% of first switches pick a random alternative for the evidence log. A code-checked wrong answer counts on the same turn; otherwise the model gets a fallback one turn early (no lag). |
| New strategies | `pedagogy.STRATEGIES` | MULTIPLE_METHODS, WHEN_TO_USE, CONNECT_REPRESENTATIONS, JUSTIFY_AND_CHECK (TMU) |
| State record | `state.py`, `prompts.py` | + `level` (form the learner worked in) and `progress` (none / step_forward / solved); literal backslash-n fallback bug fixed |
| Mastery | `mastery.py` | success weighted by level: abstract 1.0, pictorial 0.5, concrete 0.3 (starting values) on top of the hint discount; `learner_events` gains `cpa_level` and `strand` |
| Evidence log | `db.py` `pedagogy_decisions`, `learner_level_stats` | every switch: trigger, kind, strategy, level, engine or random, outcome over the next 2 turns |
| Memory | `memory.py` | working problem keeps level, no-progress count, switches, bridge flag; a solved problem is closed by code (fixes "correct answer treated as a new topic") |

## Simulator

- `conversations` gains c12-c16 (CPA): stuck at abstract, steady progress (no
  switch), "show me another way", Grade 12 logs, and the full switch budget.
  New columns: `code_checked`, `switched_ok`, `switch_sequence_ok`.
- New suite `homework_day`: one learner, 7 problems in one sitting (d01 Grade 8,
  d02 Grade 12). Columns: solved share, turns and switches per problem, seconds
  per reply, calls and model cost per day, WhatsApp messages and Twilio's fee
  ($0.005 per message in or out). Meta's South African service-message fee is
  not confirmed, so it is not included.

Run (PowerShell, `Documents\TutoBuddy-cto`):

```powershell
docker compose build
docker compose up -d db redis
docker compose --profile test run --rm tests                      # unit + e2e
docker compose run --rm evals python -m evals.bench.run --stage dry --suites conversations,homework_day
docker compose run --rm evals python -m evals.bench.leaderboard --stage dry
# paid, after the Groq upgrade: prints the quote first, spends only with --yes
docker compose run --rm evals python -m evals.bench.run --stage pilot --suites conversations,homework_day --yes
```

## Known limits

- Answer checking covers equations in one variable. Fractions, integers,
  expressions, derivatives and word problems are still judged by the model.
- Photos are not simulated in `homework_day`.
- `reveal` after 3 wrong attempts / 2 answer requests (choose()) is unchanged;
  the worked example after the switch budget uses a similar problem instead.
- Level weights, the 3-turn threshold and the 10% exploration share are
  starting values to calibrate on pilot data.
- `methods.json` needs teacher review, especially the three "Katlego team" entries.
