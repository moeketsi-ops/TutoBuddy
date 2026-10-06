# Database merge: curriculum-engine → Katlego POC (database only, per founder scope)

Status: **done, per founder confirmation (2026-09-15)**. Schema merged, committed on branch `moeketsi/curriculum-database-merge` (stacked on `moeketsi/groq-ollama-provider`), image rebuilt, `seed/load_curriculum.py` run against the CTO repo's Postgres. Not pushed to GitHub. Next step (pedagogy/mastery-pace modelling and/or safety modelling) not yet started — see bottom of this doc.

## Why

Founder uploaded `TutoBuddy_Curriculum_Intelligence_Miro_Board.pptx` (the IP-stack thesis: CAPS → Structured Curriculum → Learning Objectives → Learning Graph → RAG → LLM → Katlego, with ~80% of stated value in the curriculum/objective/graph layers, only 20% in RAG+LLM). Immanuel's own `TECHNICAL_BLUEPRINT.md` in the CTO repo makes the same claim independently ("the mastery graph... is the moat; everything else is plumbing").

Code audit of the CTO repo (`app/tutor/rag.py`, `app/orchestrator/session.py`, `app/db.py`, `seed/seed.py`) confirmed the actual implemented POC is a flat `caps_chunks` vector-similarity RAG system — none of the curriculum/objective/graph/mastery layers exist in code, only in the two documents. The founder's own separate (non-git) `Documents\TutoBuddy` folder already has a working Postgres schema for most of those missing layers (`schema.sql`, `migration_content_areas.sql`, `migration_learner_assessment_model.sql`) plus real Grade 8 Mathematics curriculum data (`curriculum/json/grade8_mathematics.json`) — but it was never connected to Katlego.

Founder's explicit sequencing decision: **database merge only, first** — not yet rewiring retrieval, not yet building mastery/pace logic into the live tutor loop, not yet the full 4-layer safety model. Those are deferred follow-ups.

## Design decisions made

1. **`learners` table collision, resolved in favour of Katlego's live table.** The CTO repo's `learners` (phone TEXT primary key) is already wired into the POPIA consent state machine in `app/orchestrator/session.py`. The standalone engine's own `learners` (SERIAL id, whatsapp_number, grade_id FK) was **not** imported — that would create two competing identities for the same person. Instead, a nullable `grade_id INT REFERENCES grades(id)` bridge column was added to the existing table; the existing `grade int` column is untouched.
2. **`learner_topic_mastery` / `learner_assessment_attempts`** re-keyed to `learner_phone TEXT REFERENCES learners(phone)` instead of the standalone engine's `learner_id INT REFERENCES learners(id)`, to match decision 1. Both tables exist now but are empty — nothing writes to them yet (that's the mastery/pace follow-up).
3. **Schema lives in `app/db.py`'s existing `SCHEMA` string** (idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), matching the pattern Katlego already uses, rather than introducing a separate migration tool.
4. **`grades.grade_number` CHECK widened to 7–12** (the standalone engine's `schema.sql` had 8–12). The real Table 4.1/4.2 assessment seed data covers Grades 7–9, so 7 has to be a valid grade.
5. **New idempotent loader**: `seed/load_curriculum.py` (asyncpg, upsert-based — not the TRUNCATE pattern `seed/seed.py` uses, since these tables have downstream FKs a TRUNCATE would cascade-delete). Run via `docker compose run --rm seed python -m seed.load_curriculum`. Loads Grade 8 Mathematics (5 content areas, 21 topics, 2 topics with real learning objectives so far — the rest are placeholders in the source JSON) plus the Senior Phase Mathematics assessment structure (grades 7–9: SBA task weights, per-grade mark totals, cognitive-level split) ported from `migration_learner_assessment_model.sql`'s DO block.
6. **Known gap, not fixed in this pass**: `question_bank.cognitive_level` (free text, e.g. `"routine procedure"`) and the new `cognitive_level_weights.level_name` (enum, e.g. `'routine_procedures'`) use different vocabularies. Reconcile when the pedagogy/mastery layer is actually built.
7. **Known gap, not fixed in this pass**: the CTO repo's seeded `caps_chunks` RAG demo content covers Grades 10–12 (Maths/Accounting); the newly-merged curriculum data is Grade 8 only. No row-level conflict, but nothing will visibly "connect" in the live chat yet — expected, since `rag.py` rewiring is explicitly deferred.

## Files changed

- `app/db.py` — SCHEMA string extended with `phases`, `grades`, `subjects`, `documents`, `document_sections`, `content_areas`, `topics`, `subtopics`, `learning_objectives`, `skills`, `atp_schedules`, `assessment_structure`, `assessment_task_marks`, `cognitive_level_weights`, `learner_topic_mastery`, `learner_assessment_attempts`, plus the `learners.grade_id` bridge column.
- `seed/load_curriculum.py` (new) — the loader described above.
- `seed/curriculum/grade8_mathematics.json` (new) — copy of the founder's real Grade 8 Mathematics curriculum data.

Committed on `moeketsi/curriculum-database-merge` (stacked on `moeketsi/groq-ollama-provider`), local only — not pushed to GitHub.

## Branch / repo situation

Only one repo exists: Immanuel's `immanueln98/TutoBuddy`, cloned locally by the founder to `Documents\TutoBuddy-cto`. There is no separate "founder's repo." A true separate fork would need the founder to do that on github.com under his own account.

## Next step (not started)

Founder's own framing: "refine the model into how the pedagogy model + mastery pace modelling could look like and safety modelling when chats start with the bot." Two distinct pieces of work, not yet sequenced against each other:
- **Pedagogy / mastery-pace model**: wire `app/tutor/rag.py` to use the new structured curriculum (learning objectives, content-area weighting) instead of flat `caps_chunks`, and start writing to `learner_topic_mastery` / `learner_assessment_attempts` so the mastery bands (remediate/practice/challenge/advance) actually reflect real learner activity.
- **Safety modelling**: `app/orchestrator/safety.py` currently only implements layer 1 of the 4-layer model already resolved in `technical-blueprint-reconciliation.md` (input keyword-scan only — no output-safety layer, no human-escalation/review queue, no age-band logic).
