# Memory, mastery and pedagogy v1 (branch `moeketsi/memory-pedagogy`)

Status 16 Oct 2026: built and tested on the stub (80 tests green, bench dry
stage green). Not yet run on a real model. Full spec with the reasoning:
"Katlego memory + pedagogy spec v0.1" (project doc). This file is the
short version the code comments cite.

## The problem it fixes

Before this branch every WhatsApp message reached the model alone
(`_complete` sends one system + one user message). Katlego asked "what
could you do to both sides?", the learner replied "minus 5?", and the model
saw "minus 5?" with no equation. Mastery only moved on "quiz me" answers.
The pedagogy engine existed only on paper.

## What a turn does now (still ONE model call)

1. `memory.load(learner_id)`: Redis `mem:{learner_id}`, keyed by learner,
   never phone (siblings share `sess:{phone}`).
2. A short reply to the working problem (`memory.continues_problem`) skips
   the intent router and keeps the working topic; retrieval searches with
   the problem attached.
3. `pedagogy.with_fallback()` picks the strategy, hint level and reveal
   rule in code, plus a fallback "if this attempt is wrong too, use Y".
4. One Socratic call. The prompt carries a MEMORY block (learner, topic,
   LO mastery, working problem, code-built digest of earlier work, last 2
   turns) and ends by asking for a hidden STATE line.
5. `state.strip_state` / `parse_state`: the line is removed before sending
   and every field validated against closed lists. Invalid = no evidence,
   never a broken reply.
6. `mastery.record_event`: evidence moves the LO score
   (`m += w * (t - m)`), rolls up to `learner_topic_mastery`, and
   `learner_strategy_stats` credits the strategy that prompted the attempt.
7. `memory.record_turn`; every 5 turns or on a topic change the oldest
   turns roll into one digest line written by code and saved to
   `learners.memory_digest`.

## Design choices worth reviewing

| Choice | Why | Alternative rejected |
|---|---|---|
| STATE line piggybacks on the tutoring call | Judging the attempt costs ~30 output tokens, not a second ~600-token call | Mem0-style extraction call per message |
| Numbers written by code only | Mastery must be exact and replayable (`learner_events`) | LLM-written memories |
| Thompson sampling over strategies, ladder order with no data | Learns per learner x topic what works, zero tokens, predictable for new learners | Fixed "visual learner" labels |
| Fallback strategy in the prompt | Code can't judge the message before the call; this removes a one-turn lag | Decide after the call (needs a second call) |
| Pre-call regex for "give me the answer" | Second request is honoured on the same turn | Wait for STATE (one turn late) |
| Digest built from STATE data, no LLM | Free and can't invent anything | LLM summary (planned as step 4, with soft facts) |
| Placeholder LO per topic (`TOPIC-<id>.00`) | LO-level tables work today with 5 real LOs | Topic-level only |

## Numbers (stub estimates, chars / 4)

Socratic prompt about 1,100 tokens on average across the test conversations
(was about 880 without memory). Real numbers come from `llm_calls` once
`LLM_PROVIDER=openrouter` runs.

## For the bench

- New suite `conversations` (8 scripted Grade 8 learners, 3 to 4 turns):
  `state_valid`, `strategy_follow`, `judged_right` (did the model's ev label
  match the truth label), `leak_early`, `on_problem`, `tokens_per_turn`.
  Stub floor: 100% / 100% / about 60% / 0% / 100%.
- `llm._record` call sites became `await _emit(...)`: same capture list,
  plus a row in `llm_calls` for live traffic (billed cost when OpenRouter
  returns it). The bench's own numbers are unchanged.
- The single-turn `tutoring` suite calls `tutor_reply(..., None)` and gets
  the stateless path (no memory, no STATE), so its rows stay comparable;
  the prompt version is now `socratic-v4`. Two changes do reach that path:
  rule 7 (specific praise, not generic) and the reply cap of 400 tokens
  instead of 600 (a 120-word reply is about 160). Rerun the tutoring suite
  before comparing against older rows.

## Not in this branch

LLM-written summary and soft facts (step 4), idle-time sweep, diagnostic at
first chat, real learning objectives per topic, misconception list per
topic beyond the 10 cross-topic codes.

## Update 16 Oct: structured output and CAPS objectives

**Structured output replaces the STATE line as the default** (founder
decision; `STRUCTURED_OUTPUT=json`). The tutoring call returns one JSON
object, `{"state": {...}, "reply": "..."}`, state first so the model judges
the learner's message before writing the reply. The schema is built per
turn (`state.turn_schema`): `lo`, `misc` and `strat` are enums of THIS
turn's candidates, so a schema-enforcing provider cannot return an unknown
code. Sent as OpenAI-style `response_format` json_schema strict (OpenRouter
with `provider.require_parameters=true`, Groq), Anthropic
`output_config.format`, Ollama `format`.
Fallbacks, in order: provider refuses the schema -> same prompt without it
("json_prompt"); output isn't JSON -> STATE line parser; JSON that won't
parse -> only its "reply" string, or the turn fails (raw JSON is never sent).
`llm_calls.output_mode` and the bench's `structured` metric show which path
each model actually takes. Not yet confirmed: whether OpenRouter's hosts for
qwen/qwen3.5-35b-a3b honour json_schema (the bench will show it).

**CAPS learning objectives for Grades 8-12** (384 new, plus the 5 existing
Grade 8 algebra ones): `seed/curriculum/objectives/*.json`, loaded by
`python -m seed.load_learning_objectives`. Grade 8/9 from CAPS Senior Phase
s.2.7 (phase overview, one LO per bullet); Grade 10-12 from CAPS FET s.3.2.3
(numbered curriculum statements, with term). Extracted from the DBE PDFs'
text layer, wording kept, each file re-checked against its source. 25 LOs
whose maths notation could not be restored with certainty load with
`needs_review = true`. A teacher review is still owed.

**Scoring** (`mastery.objective_progress`, shown by PROGRESS): coverage =
objectives with evidence; understanding = mean mastery over covered
objectives; both weighted by the topic's CAPS teaching hours in the term.
The tutor gets at most 6 LO candidates per turn, ranked by word overlap
with the question (+ the LO in play).
