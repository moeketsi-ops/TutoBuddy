# Progress summary — `moeketsi/household-safety-pedagogy`

Branch base: `main`, current at commit `8c9985b` (10 commits ahead, listed below). Built by Moeketsi with Claude (Cowork) over several sessions, working directly against this repo (`Documents\TutoBuddy-cto` on his machine). This file exists so you (Immanuel) have one place to review everything before it's considered for merge — it is NOT a description of a finished, production-ready feature set; several known gaps are called out explicitly below and should be read before testing.

## How to build and test this branch

```powershell
docker compose build
docker compose up -d --force-recreate gateway worker
docker compose run --rm seed python -m seed.load_curriculum
docker compose run --rm seed python -m seed.load_past_papers
docker compose run --rm seed python -m seed.migrate_to_household_accounts   # destructive, one-time — see below
docker compose run --rm tests
```

**Two gotchas that cost real debugging time and are worth knowing up front:**

1. `docker-compose.yml` puts `seed`, `evals`, and `tests` on Compose *profiles* (`["tools"]` / `["test"]`), while `gateway`/`worker`/`mockwa`/`stt`/`db`/`redis` have no profile (always active). A bare `docker compose build` or `docker compose up` silently skips the profiled services — you have to name them directly (`docker compose build seed`) or pass `--profile tools` / `--profile test`. This bit us more than once; worth deciding whether that's intentional or should be changed.
2. `seed/migrate_to_household_accounts.py` is a **destructive, one-off, manually-run** migration (drops and recreates `learners`, `learner_topic_mastery`, `learner_assessment_attempts` in the new shape — see "Household account model" below). It wipes any existing learner/mastery/attempt data in whatever database you run it against. Fine for a dev DB with only test data in it; do not run it against anything with real data without a real backfill plan, which does not exist.

## What's in this branch, commit by commit

| Commit | What |
|---|---|
| `cbb8103` | Groq + Ollama as LLM providers alongside Anthropic/stub |
| `ee9fa07` | Merge in the curriculum-engine schema (CAPS structure, learning objectives, assessment weighting) |
| `8eaf7a5` | Term-progress reporting + mastery-aware practice questions |
| `80ef879` | Fix: `documents.grade_id`/`subject_id` needed `ALTER TABLE`, not `CREATE TABLE IF NOT EXISTS` (the table already existed) |
| `46540d2` | OpenRouter provider for Qwen3.5-35B-A3B (reasoning + vision) |
| `578c782` | 4-layer child-safety architecture (`safety.py`/`safeguarding.py`) |
| `edd9019` | Explicit "what's your name?" onboarding step |
| `51e7cf0` | Phase 1 household account model: `learners` goes from phone-keyed to account/guardian/learner |
| `be54ebd` | Fix: the migration script above couldn't reach its own `DROP TABLE` step — see below |
| `8c9985b` | Close the mastery loop: practice answers are now graded and actually update `learner_topic_mastery` |

## 1. Groq / Ollama / OpenRouter providers

Your original code only supported `stub` (offline canned replies) and `anthropic`. Added three more `LLM_PROVIDER` options in `app/config.py`/`app/adapters/llm.py`:

- **groq** — free/cheap hosted `openai/gpt-oss-20b`/`120b`, same two-tier router/reasoner split as Anthropic. No vision support.
- **ollama** — fully local/offline via a locally-running Ollama server (`host.docker.internal`), no API key. Model names in `.env.example` are a guess (`llama3.2`), not a verified default — whoever uses this should check `ollama list` first.
- **openrouter** — OpenAI-compatible API, one key across many hosted models. Wired up specifically for **Qwen3.5-35B-A3B** (open-weight MoE, ~3B active params) because it's genuinely multimodal — this is the only non-Anthropic provider that also powers `photo_reply` (homework photos). Model existence/specs verified against Alibaba's own docs and OpenRouter's listing before wiring it up (it postdates older training data, so this wasn't assumed from memory).

**Design constraint worth knowing**: `LLM_PROVIDER` is one switch that routes *everything* — intent classification, Socratic replies, practice questions, and vision all move to whichever provider it's set to. There's no way yet to mix providers per tier (e.g. cheap Groq for intent routing, OpenRouter/Qwen only for vision). That's a real limitation if cost matters — decoupling it (a separate `VISION_PROVIDER` setting, say) would be a small, contained follow-up if wanted.

## 2. Curriculum database merge

Your live schema (`app/db.py`) only had a flat `caps_chunks` vector-similarity table — no curriculum graph, no learning objectives, no mastery tracking, despite `TECHNICAL_BLUEPRINT.md` describing the mastery graph as the actual moat. Merged in the schema and real Grade 8 Mathematics data from a separate (non-git) curriculum-engine effort: `phases`, `grades`, `subjects`, `documents`, `document_sections`, `content_areas`, `topics`, `subtopics`, `learning_objectives`, `skills`, `atp_schedules`, `assessment_structure`, `assessment_task_marks`, `cognitive_level_weights`, `learner_topic_mastery`, `learner_assessment_attempts`.

Deliberate scope decision at the time: **database only** — not yet rewiring `rag.py`'s retrieval to use this instead of `caps_chunks`, not yet writing to mastery (that came later, see §7). Your existing `learners` table (phone-keyed, wired into the POPIA consent flow) was kept as the identity source of truth rather than importing the standalone engine's separate `learners` table — a nullable `grade_id` bridge column was added instead of creating two competing identities for the same person.

**Known gap, unresolved**: `question_bank.cognitive_level` (free text) and the new `cognitive_level_weights.level_name` (enum) use different vocabularies — not reconciled.

## 3. Term-progress reporting + mastery-aware practice questions

Wired `app/tutor/rag.py` to read the new curriculum tables: `get_term_progress()` (per-topic mastery/band, ranked heavily-weighted-and-weak first), `pick_practice_topic()`, `get_past_paper_excerpts()` (real OCR'd past papers, loaded via new `seed/load_past_papers.py` — 10 PDFs, 116 pages, OCR'd with `tesseract`; text/prose OCR'd reliably, **math notation degrades** — fractions/exponents/multi-step arithmetic come out mangled, e.g. `3 − (−3) + 8` → `3---3+8-1-7+12+1`). Because of that, past-paper excerpts are never shown to or quoted at a learner — they're passed to the LLM as style/topic reference only, with an explicit instruction to write and solve an ORIGINAL question rather than trust any OCR'd digit (`prompts.practice_system`).

New `PROGRESS` command and `quiz`-intent routing in `app/worker.py`. At this point in the branch, mastery scores were still permanently empty — see §7 for why and how that's since been fixed.

## 4. `documents.grade_id`/`subject_id` fix

Small but instructive bug: these columns were added via `CREATE TABLE IF NOT EXISTS`, which is a no-op against a table that already exists — regardless of column mismatch. Needed `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` instead. Same bug class recurred once more later (§8) and is worth being generally alert to in this codebase, since the whole schema lives in one big idempotent SQL string in `app/db.py`.

## 5. 4-layer child-safety architecture

`TECHNICAL_BLUEPRINT.md` already specified a 4-layer model (input safety → AI tutor → output safety → safeguarding); only layer 2 (AI tutor) and a flat keyword-scan version of layer 1 existed in code. Built out layers 1, 3, and 4:

- **Layer 1** (`safety.classify_risk`): categorised (not just boolean) — `self_harm` / `abuse_disclosure` pattern sets, so a flagged message records *why*. New `redact_pii()` strips SA ID numbers/emails/phone numbers from what's written to `conversation_log` (the tutor itself still sees the learner's real message — minimisation is about storage, not about answering).
- **Layer 3** (`safety.sanitize_output`): runs on every LLM-generated reply before sending — strips any URL the model produces, and re-scans the model's own output against the same risk categories as layer 1 (defense-in-depth; not the expected path, but the model's own text is never trusted blindly either).
- **Layer 4** (new `app/orchestrator/safeguarding.py` + `safeguarding_flags` table): every flagged case is persisted (category, excerpt, status, timestamps) and, if `SAFEGUARDING_ALERT_PHONE` is set, pushed immediately over WhatsApp to a real human. If not configured or the send fails, it's logged at `CRITICAL` rather than silently dropped. Deliberately **not** foreign-keyed to `learners` with cascade delete — a duty-of-care record must survive a POPIA deletion request, unlike ordinary learner data.

**Known gaps, flagged not fixed**: homework photo *content* isn't moderated, only the text caption; this is regex/keyword-based, not a trained classifier (some real disclosures phrased unusually will slip through — false negatives are the risk that matters more than false positives here); one alert phone number with no review/assignment workflow (fine solo, not once there's a team); not yet run through `docker compose run --rm tests` against these specific changes (each piece was reasoned through manually, not test-suite-verified) — worth doing before trusting this.

## 6. Onboarding: explicit name step

Small UX fix, landed just before the household model work below: onboarding now explicitly asks "what's your name?" rather than inferring identity implicitly, since it wasn't clear to a real user that a profile was being created. This anticipated needing a real name field once profiles became multi-learner (§7).

## 7. Household account model (Phase 1)

**The core problem, confirmed directly in the code before this**: `learners` had `phone text PRIMARY KEY` — one WhatsApp number *was* one learner, full stop. Two siblings sharing a parent's phone (common, arguably the median household in this market, not an edge case) could not both use Katlego; the second child's messages would silently overwrite the first child's grade and mastery history on the same row.

Restructured to **account (household) → guardian(s) (consent) → learner(s) (education/mastery entity) → WhatsApp channel** (phone demoted to just a channel under the account, not identity). New tables: `accounts`, `account_channels`, `guardians`, `guardian_learner`. Redesigned `learners` (id-keyed, no `phone` column) and re-keyed `learner_topic_mastery`/`learner_assessment_attempts` from `learner_phone` to `learner_id`. New commands: `ADD LEARNER` (add a sibling under the same household, no new consent gate), `SWITCH` (change active learner by name or number), `DELETE` now removes only the active learner (switches to a sibling if any remain).

**Scope, deliberately limited**: no PIN-based profile authentication, no inactivity session lock, no separate "parent mode" (all deferred to a Phase 2 — none of them block proving the core multi-learner data model). No real per-child consent capture yet either — one guardian's consent currently covers every learner they add under the household (the schema has a `consent_given_at` column ready for that later, just not wired up). "Study Rooms" (shared WhatsApp-group study sessions) are a separate Phase 3, blocked on WhatsApp's Official Business Account Groups API — confirmed via Meta's own docs this is capped at 8 participants per group and invite-link-only, so it will only ever work for small pods, never a whole class.

**Bug caught before shipping**: `RESET` only ever cleared the Redis session state, never the Postgres rows — a naive "always create a new household" implementation would have produced a duplicate orphaned `accounts`/`guardians` row every time someone reset and re-agreed. `create_household()` is idempotent — it looks up any existing channel→account mapping for the phone first.

Since this branch also touches identity end-to-end, the full onboarding → sibling → switch → delete → practice flow should get a real manual retest before merge, not just the automated suite.

## 8. Migration script bug (fixed same day)

The migration script in §7 (`seed/migrate_to_household_accounts.py`) originally called `get_pool()` to get a database connection — but `get_pool()` itself calls `ensure_schema()` before handing back a connection, and `ensure_schema()` runs the **entire new schema**, including a `CREATE INDEX` on `learners.account_id`. Since the whole point of the migration is to drop the *old* `learners` table first, that index creation crashed immediately (`UndefinedColumnError: column "account_id" does not exist`) before the migration's own `DROP TABLE` statements ever ran — a chicken-and-egg bug. Fixed by connecting directly with `asyncpg` instead of `get_pool()`, so the drop happens before any schema check.

## 9. Mastery loop closed

Until this commit, `learner_topic_mastery` was permanently empty — the progress/practice code from §3 only ever *read* it, nothing wrote to it. This closes that loop:

- `practice_system`'s prompt contract changed from freeform text to a parseable `QUESTION:`/`FINAL_ANSWER:` pair, so the model's own worked answer is captured server-side as ground truth (never shown to the learner).
- New `grade_practice_answer()` grades the learner's free-text reply against that ground truth (correct/partial/incorrect), falling back to judging on merit if parsing the ground truth failed.
- New `record_practice_attempt()` upserts `learner_topic_mastery` (clamped 0–100, a simple +12/+4/−6 delta by correct/partial/incorrect — an explicit placeholder heuristic, not a calibrated model, flagged in code comments to revisit once there's real attempt volume) and logs every attempt to a new `learner_practice_attempts` table (kept separate from `learner_assessment_attempts`, which is tied to formal CAPS `assessment_structure` tasks, not ad-hoc WhatsApp practice questions).
- A pending practice question is now stashed per-session so the learner's next message is graded as their answer, not reclassified as a new question. Added a `SKIP` command.
- **Bug caught before shipping**: the pending question was being stored in the household-wide session, but a practice question belongs to one specific learner. Every place the active learner changes (`SWITCH`, `DELETE`, `ADD LEARNER`) now explicitly clears it, or a sibling's answer could have been graded against a different learner's question and corrupted the wrong learner's mastery score.

This was the first deliberate increment of a larger "Dynamic Pedagogy Engine" design (strategy-effectiveness tracking, an adaptive intervention threshold, richer structured feedback, eventually facilitated multi-learner "Study Rooms") that Moeketsi and Claude have been designing but have NOT started building beyond this — happy to share that design doc separately if useful context for where this is headed.

## What this branch does not touch

No changes to the gateway/webhook layer, the mock WhatsApp Cloud API, the STT pipeline, or the eval harness's grading logic itself (only its stub-detection helper, from the Groq/Ollama commit). `evals/golden.json` has not been run against any of these changes — there's no accuracy number yet for how any of the new providers or the mastery-aware practice questions perform against your NSC-style golden set.

## Straightforward follow-ups if this gets merged

1. Run `docker compose run --rm evals` (also profile-gated — see the compose gotcha above) against whichever provider you settle on, to get a real accuracy baseline before/after these changes.
2. Decide on the `docker-compose.yml` profiles question — intentional friction or worth relaxing so `seed`/`tests` build by default.
3. Reconcile the `cognitive_level` vocabulary mismatch flagged in §2.
4. Full manual retest of the household flow (§7) plus `docker compose run --rm tests` before treating Phase 1 as stable.
