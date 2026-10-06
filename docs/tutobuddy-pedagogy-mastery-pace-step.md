# Pedagogy step: term-progress reporting + mastery-aware practice questions

Status: committed and running (`moeketsi/curriculum-database-merge`). Builds directly on `tutobuddy-database-merge-decision.md`. The "nothing writes to mastery" gap flagged below is now closed — see the "Mastery loop closed" section at the end.

## Founder's ask

Wire `rag.py` to (1) pull learner topic mastery and report term-topic progress, and (2) pull past-paper content to generate practice examples during "practising" moments. Safety.py deferred to a separate step.

## Scope-clarifying decisions (asked, founder chose)

1. **Progress bar scope**: founder chose *backend only* — the bot reports progress as WhatsApp text (an emoji progress bar + per-topic breakdown), not a new web dashboard. The dotkids.co.za screenshots he shared were reference/inspiration, not a build target — Katlego still has no web frontend, only WhatsApp + the `/demo` simulator.
2. **Past-paper quality**: founder chose to *use the raw OCR'd past papers anyway*, despite the known math-notation corruption flagged in `tutobuddy-past-papers-ocr-pipeline.md` (fractions/exponents/multi-step sums garbled — confirmed again first-hand reading a real memo page: "9.2 25 4.1.1 iad 3 oe" for what should be a clean fraction). **Mitigation applied, not asked for verbatim**: past-paper excerpts are never served or quoted to a learner. They're passed to the LLM as loose style/topic reference only, with an explicit instruction (`prompts.practice_system`) to write and solve an ORIGINAL question in the same spirit rather than trust any OCR'd digit. This lets the founder's "use them anyway" choice stand without risking a wrong worked example reaching a real kid.

## What was built

**Schema additions** (`app/db.py`): `documents.grade_id`/`subject_id` bridge columns; `document_sections.topic_id` (best-effort tag) and `.embedding` (pgvector), added via `ALTER TABLE` after `topics` exists in the script (ordering constraint — `document_sections` itself is created earlier in the file).

**`app/tutor/rag.py`** (the file the founder named) — `retrieve()` untouched. Added:
- `get_term_progress(phone, grade, term, subject)` — per-topic mastery/band for the term, ranked heavily-weighted-and-weak first (same ordering as the reference query in `migration_learner_assessment_model.sql`), plus coverage % and average mastery.
- `pick_practice_topic(progress)` — takes the top-ranked topic.
- `get_past_paper_excerpts(topic_name, grade, k)` — pgvector similarity search over `document_sections` filtered to `document_type='past_paper'` and grade; every result carries `verified: False`.

**`app/tutor/prompts.py`** — `progress_message(progress)` (pure text formatting of real DB numbers, no LLM call — nothing here can be hallucinated); `practice_system(grade, topic, band, excerpts)` (the anti-hallucination system prompt described above).

**`app/adapters/llm.py`** — `practice_question(...)`, same anthropic/groq/ollama/stub branching as the existing `socratic_reply`/`direct_answer`.

**`app/tutor/engine.py`** — `current_term()` (rough SA-calendar term-from-date heuristic — not real gazetted dates), `progress_reply(...)`, `practice_reply(...)`.

**`app/worker.py`** — two small wiring changes, needed because "practice moments" are decided by the existing intent classifier, which lives here, not in rag.py: added a `PROGRESS` text command (same pattern as `HELP`/`RESET`/`DELETE`), and routed the already-existing `quiz` intent value (previously classified but unused — everything fell through to the regular tutor reply) to `practice_reply`. HELP_MESSAGE updated to mention both. No changes to consent, safety, or onboarding logic.

**`seed/load_past_papers.py`** (new) — loads the founder's 10 OCR'd Grade 8 Mathematics past-paper JSON files (copied in from the standalone curriculum-engine repo's `data/processed/past_papers/`) into `documents`/`document_sections`, with a simple keyword-based best-effort topic tag and an embedding per page. Idempotent by document title (skips already-loaded files). Requires `load_curriculum.py` to have run first (needs its Grade 8/Mathematics rows).

## Known gaps / not done

- Topic tagging on past-paper pages is a plain keyword substring match, not verified per page — some pages will be mistagged or untagged (untagged pages still get found via embedding similarity alone).
- `current_term()` is a rough calendar guess, not real ATP term dates.
- ~~Nothing yet writes TO `learner_topic_mastery`~~ — closed, see below.
- `safety.py` untouched at the time this step shipped; a full 4-layer implementation followed in a later session (`tutobuddy-safety-four-layer-implementation.md`).

## Mastery loop closed (later session, commit `8c9985b`)

First build increment of the Dynamic Pedagogy Engine design (`tutobuddy-dynamic-pedagogy-engine-design.md`) — chosen deliberately as the *first* increment because nothing else in that design (strategy-effectiveness tracking, the intervention score, "multiple paths to mastery" scoring) can be honestly built on mastery data that never updates.

- `practice_system`'s output contract changed from freeform prose to a parseable `QUESTION:`/`FINAL_ANSWER:` pair (PROMPT_VERSION bumped to `socratic-v2`) — the model's own worked answer is now captured server-side as ground truth, never shown to the learner.
- New `grade_practice_answer()` (+ `grade_practice_system` prompt) grades the learner's free-text reply against that ground truth (or, if parsing failed and no ground truth was captured, judges on merit and leans toward "partial").
- New `record_practice_attempt()` in `rag.py` upserts `learner_topic_mastery` (clamped 0–100; a learner with no prior score starts at a neutral baseline of 50, which already lands in the "practice" band) and logs every attempt to a new `learner_practice_attempts` table — kept separate from `learner_assessment_attempts`, which is tied to formal CAPS `assessment_structure` tasks, not ad-hoc WhatsApp practice questions.
- Mastery deltas (+12 correct / +4 partial / −6 incorrect) are an explicit placeholder heuristic, not a calibrated model — flagged in code comments to revisit once there's real attempt data.
- Session wiring: a pending practice question is now stashed per-session (`pending_practice`) so the learner's next message is graded as their answer rather than reclassified as a fresh question. Added a `SKIP` command to drop a pending question without answering it.
- **Bug caught before shipping**: `pending_practice` lives in the household-wide session, but a practice question belongs to one specific learner. Every place `active_learner_id` changes (`SWITCH`, `DELETE`, `ADD LEARNER`) now explicitly clears it — otherwise a sibling's answer, or the learner switched to, could have been graded against a different learner's question and updated the wrong learner's mastery score.
- New `tests/test_practice.py` (E2E, using a Grade 8 learner since only Grade 8 Term 3 topics are currently seeded — inherits the same calendar-dependency caveat as `current_term()` itself).

Not yet built (deliberately out of scope for this increment, per the founder's own sequencing choice): the strategy library, per-strategy effectiveness tracking, the pedagogy decision object, wait-time/interaction modes, structured feedback objects beyond the minimal correct/partial/incorrect split used here. See `tutobuddy-dynamic-pedagogy-engine-design.md`'s "relationship to what's already built".

### Run sequence (founder, in PowerShell from `Documents\TutoBuddy-cto`)

```powershell
docker compose build
docker compose up -d --force-recreate gateway worker
docker compose logs worker --tail 30   # confirm clean startup, no traceback
```

Then retest via `/demo`: "quiz me" → answer it → expect a ✅/➗/❌ feedback message. Full automated coverage: `docker compose run --rm tests` (or `docker compose --profile test run --rm tests` — see the profiles gotcha in `tutobuddy-household-account-model-phase1-plan.md`).
