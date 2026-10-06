# Household account model — Phase 1 implementation plan

Status: **built, committed `51e7cf0`** (2026-09-17). Not yet run/tested by the founder — the one-off migration and a full rebuild/retest are still owed (see "Next steps" at the bottom, updated).

This is the concrete build plan for the account/guardian/learner architecture from `tutobuddy-account-model-household-learners.md`, scoped to what's buildable now. Adapted from a standard planning template: no subagent/worktree handoff section, since this was built directly in this session rather than handed to a separate engineer — the "plan" here is the architecture, schema, and phase boundaries, not a bite-sized step-by-step script.

## Scope: what Phase 1 is and isn't

**Phase 1 (built):** the real data model — `accounts` → `guardians` + `learners` (many per account) → mastery per learner — plus a rewritten onboarding flow that creates a household on first consent, creates learners under it, and lets an active learner be switched by name. No PIN. No inactivity lock. No Study Rooms.

**Deliberately deferred to Phase 2:** PIN-based profile authentication (hashed, argon2id/bcrypt), inactivity-based session lock, a separate "parent mode" for progress queries. Reason: each is a real sub-feature on its own (PIN issuance/recovery flow, lock timing/UX, parent-vs-learner command surface) and none of them block proving the core multi-learner data model end to end.

**Deferred to Phase 3, blocked on external setup:** Study Rooms. Needs a WhatsApp Official Business Account application/approval for the Groups API before any code here matters (max 8 participants, invite-link only, per `tutobuddy-account-model-household-learners.md`'s fact-check).

**Phase-1 simplification, stated explicitly (not hidden):** one guardian's consent covers every learner they add under the same household in this phase — there's no separate per-child consent capture UI yet, even though `guardian_learner` has its own `consent_given_at` column ready for that later.

## What actually shipped vs. the original plan (two deltas)

1. **Dropped `learners.grade_id`** from the new table. The plan sketch included it (mirroring the old bridge column), but a grep before building confirmed nothing anywhere in the codebase ever reads `grade_id` — only the plain `grade int` column is used by session.py/rag.py. Adding a dead column back would've been carrying forward cruft for no reason, so it's gone; `grade int` is the only grade field on `learners` now.
2. **`create_household()` is idempotent**, which wasn't in the original plan. While writing it, a real bug surfaced: RESET only clears the Redis session, never the Postgres account/guardian/learner rows, so a learner who RESETs and replies AGREE again would otherwise get a second, orphaned `accounts`/`guardians` row under the same phone. Fixed by having `create_household()` look up an existing `account_channels` row for the phone first and reuse its account + oldest guardian, only creating fresh rows for a genuinely new number.

## Schema (as built)

New tables: `accounts`, `account_channels` (phone → account, `UNIQUE(channel, phone)`), `guardians`, `guardian_learner` (per-learner consent link).

Redesigned: `learners` (id-keyed, `account_id`, `nickname`, `grade` — no `phone`, no `grade_id`), `learner_topic_mastery` / `learner_assessment_attempts` (re-keyed from `learner_phone` to `learner_id`).

Additive: `conversation_log.learner_id` (nullable — attributes a row to whichever learner was active when it was sent; onboarding messages predate any learner), `safeguarding_flags.learner_id` (snapshot, deliberately not FK'd, same reasoning as the existing `phone` snapshot — a duty-of-care record must survive learner deletion).

**Migration mechanics, unchanged from the plan and important:** the redesigned tables could not be a plain `CREATE TABLE IF NOT EXISTS` edit — `learners` already existed with `phone text PRIMARY KEY` on any provisioned dev DB, and `CREATE TABLE IF NOT EXISTS` is a no-op against an existing table regardless of column mismatch (the same class of bug as `documents.grade_id`, fixed earlier this session). The drop-and-recreate lives in a **separate, one-off, manually-run script** — `seed/migrate_to_household_accounts.py` — never inside `app/db.py`'s `SCHEMA` string, which `ensure_schema()` re-runs on every service boot; a `DROP TABLE` there would wipe data on every restart forever.

**This wipes existing local test data** — every learner profile, mastery score, and practice attempt in the founder's dev database from this session's testing. Expected and accepted for a pre-launch POC.

## Identity/session model (as built)

`app/orchestrator/session.py`: `create_household(phone) -> tuple[account_id, guardian_id]` (idempotent, see above), `account_for_phone(phone)`, `add_learner(account_id, guardian_id, nickname) -> learner_id`, `set_learner_grade(learner_id, grade)`, `list_learners(account_id) -> [{id, nickname, grade}, ...]`, `match_learner(text, learners)` (1-based index or case-insensitive nickname), `delete_active_learner(learner_id)` (deletes that learner's `conversation_log` rows + the `learners` row; FK cascade handles mastery/attempts/`guardian_learner`; does NOT touch `safeguarding_flags`).

Redis session data (`sess.data`, per phone) grew from `{state, grade}` to `{state, account_id, guardian_id, active_learner_id, grade, name, onboarding_reason}` — grade/name stay denormalized copies refreshed on every write, so `Session.grade`/message handling stay synchronous.

## State machine (as built)

`"" → awaiting_consent → awaiting_name → awaiting_grade → active`, plus a `choosing_learner` micro-state for SWITCH. `onboarding_reason` (`"new_household"` vs `"add_learner"`) tracks which welcome message to send once grade capture finishes, since `awaiting_name`/`awaiting_grade` are reused for both the very first learner and any sibling added later via ADD LEARNER.

New commands in `active`, beyond HELP/RESET/PROGRESS: **ADD LEARNER** (re-enters `awaiting_name` under the same household, no new consent gate), **SWITCH** (lists learners, `choosing_learner` state, match by number or nickname; if only one learner exists, says so instead of prompting), **DELETE** (now removes only the active learner — switches to a sibling if any remain, otherwise re-enters `awaiting_name` rather than the full `""` consent reset, since household consent already stands).

`app/tutor/rag.py`'s `get_term_progress` and `app/tutor/engine.py`'s `progress_reply`/`practice_reply` all take `learner_id` instead of `phone`.

## Test changes made

`tests/test_onboarding.py`: rewrote the DELETE test (now expects "deleted + re-ask for a name", not "deleted + full POPIA reset"), added ADD LEARNER + SWITCH round-trip and single-learner-SWITCH tests. `tests/test_tutoring.py`: fixed `test_grade_filter_never_retrieves_above_learner_grade`, which the earlier name-step commit (`edd9019`) had **already silently broken** by skipping the new name step — missed at the time, caught during this pass's test-file audit before it could ship broken twice. `tests/conftest.py`'s `onboarded_chat` fixture needed no further change (same visible consent → name → grade sequence, just a different backend underneath).

## Next steps (updated)

1. Founder runs the one-off migration: `docker compose build && docker compose run --rm seed python -m seed.migrate_to_household_accounts` — destructive, one-time, wipes existing test learners/mastery.
2. Rebuild + restart: `docker compose up -d --force-recreate gateway worker`.
3. Retest the full flow in `/demo`: onboarding (consent → name → grade), then `ADD LEARNER` to create a sibling, `SWITCH` between them, `PROGRESS`/quiz-me for each, `DELETE` both with and without a sibling remaining, and a maths question/photo — all of it, since this touches the identity layer everything else sits on. `docker compose run --rm tests` covers most of this automatically.
4. Phase 2 (PIN + lock + parent mode) and Phase 3 (Study Rooms) stay queued in `tutobuddy-account-model-household-learners.md`.
