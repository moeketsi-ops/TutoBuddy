# Design records

Decision and design notes that code comments in `app/`, `seed/` and `tests/`
cite by file name. Exported from the founder's TutoBuddy project notes on
2026-10-06 (Immanuel's branch-update ask). Each note is a dated record:
"status", "next steps" and branch names describe the moment it was written,
not the current state of `main`.

| File | What it records | Cited from |
|---|---|---|
| `tutobuddy-household-account-model-phase1-plan.md` | Accounts / guardians / many learners per phone; onboarding state machine; why the migration is a one-off script | `app/orchestrator/session.py`, `app/tutor/*`, `seed/migrate_to_household_accounts.py` |
| `tutobuddy-database-merge-decision.md` | Merging the curriculum-engine schema into Katlego's Postgres | `app/db.py` |
| `tutobuddy-past-papers-ocr-pipeline.md` | Scanned Grade 8 past papers, OCR pipeline, why excerpts are never shown as fact | `app/tutor/rag.py`, `seed/load_past_papers.py` |
| `tutobuddy-pedagogy-mastery-pace-step.md` | Term progress, practice questions, closing the mastery loop | `app/tutor/*` |
| `tutobuddy-dynamic-pedagogy-engine-design.md` | Target pedagogy design (strategy library, learner model, decision object) and what is built so far | `app/tutor/*` |
| `memory-pedagogy.md` | Per-learner memory window, STATE line, evidence-weighted mastery, pedagogy engine v1, bench `conversations` suite | `app/tutor/memory.py`, `state.py`, `mastery.py`, `pedagogy.py`, `app/adapters/ledger.py` |
| `cpa-tmu-switching.md` | CPA levels, TMU strands and methods, the 3-turn switching rule, code-side answer checking, evidence log, bench CPA cases and homework day | `app/tutor/answer_check.py`, `representation.py`, `tmu.py`, `pedagogy.py`, `engine.py`, `evals/bench/run.py` |
| `technical-blueprint-reconciliation.md` | CTO blueprint vs MVP roadmap: scope, router tiers, infra, safety layers | `app/db.py`, `app/tutor/rag.py` |

Some notes mention other project notes that are not in this folder
(`tutobuddy-account-model-household-learners.md`,
`tutobuddy-safety-four-layer-implementation.md`,
`tutobuddy-curriculum-engine-phase2-ingestion.md`,
`content-sourcing-copyright-strategy.md`, `cloud-infra-big3-comparison.md`).
They are not cited by code; ask the founder if you need them.
