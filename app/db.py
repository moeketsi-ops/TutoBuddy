import asyncio

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS caps_chunks (
    id serial PRIMARY KEY,
    grade int NOT NULL,
    subject text NOT NULL,
    term int,
    topic text NOT NULL,
    doc_type text NOT NULL,
    content text NOT NULL,
    embedding vector({dim})
);

CREATE TABLE IF NOT EXISTS question_bank (
    id serial PRIMARY KEY,
    grade int NOT NULL,
    subject text NOT NULL,
    topic text NOT NULL,
    question text NOT NULL,
    memo_answer text NOT NULL,
    marks int NOT NULL,
    cognitive_level text,   -- one of app/cognitive_levels.LEVELS (CHECK below)
    source text
);
-- question_bank.cognitive_level used free text ("routine procedure") while
-- cognitive_level_weights.level_name uses the enum ("routine_procedures").
-- Migrate any old free-text rows, then enforce the same four values.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'question_bank_cognitive_level_check') THEN
        UPDATE question_bank SET cognitive_level = CASE
            WHEN lower(trim(cognitive_level)) IN ('routine procedure', 'routine procedures') THEN 'routine_procedures'
            WHEN lower(trim(cognitive_level)) IN ('complex procedure', 'complex procedures') THEN 'complex_procedures'
            WHEN lower(trim(cognitive_level)) IN ('problem solving', 'problem-solving') THEN 'problem_solving'
            WHEN lower(trim(cognitive_level)) = 'knowledge' THEN 'knowledge'
            ELSE NULL END   -- blank or unrecognised: question_bank is seed data, re-seeding restores it
        WHERE cognitive_level IS NOT NULL;
        ALTER TABLE question_bank ADD CONSTRAINT question_bank_cognitive_level_check
            CHECK (cognitive_level IS NULL OR cognitive_level IN
                   ('knowledge','routine_procedures','complex_procedures','problem_solving'));
    END IF;
END $$;

-- Household account model (see tutobuddy-household-account-model-phase1-plan.md).
-- The phone number is a CHANNEL under an account, never the learner's
-- identity -- one household can hold multiple learner profiles.
CREATE TABLE IF NOT EXISTS accounts (
    id serial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS account_channels (
    id serial PRIMARY KEY,
    account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    channel text NOT NULL DEFAULT 'whatsapp',
    phone text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel, phone)
);
CREATE INDEX IF NOT EXISTS idx_account_channels_phone ON account_channels(phone);

CREATE TABLE IF NOT EXISTS guardians (
    id serial PRIMARY KEY,
    account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Redesigned from a phone-keyed single row per number to an id-keyed row
-- per LEARNER, many per account. NOTE: if `learners` already exists from
-- before this change (phone text PRIMARY KEY), this CREATE TABLE IF NOT
-- EXISTS is a no-op against the OLD shape -- exactly the documents.grade_id
-- bug from earlier this session. A fresh database gets the new shape
-- directly; an existing one needs the one-off
-- seed/migrate_to_household_accounts.py migration run once (destructive --
-- see that script's docstring). Never add a DROP TABLE here: this whole
-- string reruns on every service boot via ensure_schema().
CREATE TABLE IF NOT EXISTS learners (
    id serial PRIMARY KEY,
    account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nickname text,
    grade int,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_learners_account ON learners(account_id);

-- Per-learner guardian consent. Phase 1 simplification: one guardian's
-- consent (given once, at household creation) covers every learner they
-- add -- there's no separate per-child consent capture flow yet, even
-- though this table is already shaped for it (its own consent_given_at).
CREATE TABLE IF NOT EXISTS guardian_learner (
    guardian_id int NOT NULL REFERENCES guardians(id) ON DELETE CASCADE,
    learner_id  int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    consent_given_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (guardian_id, learner_id)
);

CREATE TABLE IF NOT EXISTS conversation_log (
    id serial PRIMARY KEY,
    phone text NOT NULL,
    direction text NOT NULL,          -- inbound | outbound
    msg_type text NOT NULL,           -- text | audio | image | system
    content text,
    intent text,
    flagged bool DEFAULT false,
    created_at timestamptz DEFAULT now()
);

-- ============================================================
-- Curriculum engine (merged from the founder's standalone
-- TutoBuddy/database/schema.sql + migration_content_areas.sql +
-- migration_learner_assessment_model.sql). Additive only -- nothing
-- above this line is touched. CAPS -> Structured Curriculum ->
-- Learning Objectives -> Learning Graph (next) -> RAG -> LLM.
--
-- Deliberately NOT wired into app/tutor/rag.py, app/orchestrator/
-- session.py or app/orchestrator/safety.py yet -- retrieval, the
-- tutor loop and the safety model are unchanged. This is the
-- "database merge only" step; pedagogy/mastery/safety wiring is a
-- separate follow-up.
-- ============================================================

CREATE TABLE IF NOT EXISTS phases (
    id   serial PRIMARY KEY,
    name varchar(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS grades (
    id           serial PRIMARY KEY,
    phase_id     int NOT NULL REFERENCES phases(id) ON DELETE RESTRICT,
    -- widened to 7-12 (source schema.sql was 8-12): the Table 4.1/4.2
    -- assessment seed data covers Grades 7-9 of the Senior Phase.
    grade_number int NOT NULL CHECK (grade_number BETWEEN 7 AND 12),
    UNIQUE (phase_id, grade_number)
);
CREATE INDEX IF NOT EXISTS idx_grades_phase_id ON grades(phase_id);

CREATE TABLE IF NOT EXISTS subjects (
    id       serial PRIMARY KEY,
    name     varchar(255) NOT NULL,
    phase_id int NOT NULL REFERENCES phases(id) ON DELETE RESTRICT,
    UNIQUE (name, phase_id)
);
CREATE INDEX IF NOT EXISTS idx_subjects_phase_id ON subjects(phase_id);

CREATE TABLE IF NOT EXISTS documents (
    id            serial PRIMARY KEY,
    title         varchar(500) NOT NULL,
    document_type varchar(50) NOT NULL
        CHECK (document_type IN ('CAPS','ATP','textbook','past_paper','marking_memo')),
    year          int,
    file_path     text,
    source_url    text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- Bridge columns so past papers/memos can be filtered by grade/subject
-- without a join through document_sections -> topics. Nullable: a CAPS
-- or ATP document may span multiple grades/subjects. Added via ALTER, not
-- on the CREATE TABLE above -- `documents` already existed on real
-- databases (created by an earlier load_curriculum.py run) before these
-- columns were designed, and CREATE TABLE IF NOT EXISTS is a no-op against
-- an existing table, so putting them there silently did nothing on any
-- database that wasn't brand new. Same fix already applied to
-- learners.grade_id below.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS grade_id int REFERENCES grades(id) ON DELETE SET NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS subject_id int REFERENCES subjects(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS document_sections (
    id            serial PRIMARY KEY,
    document_id   int NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number   int,
    section_title text,
    content       text
);
CREATE INDEX IF NOT EXISTS idx_document_sections_document_id ON document_sections(document_id);

CREATE TABLE IF NOT EXISTS content_areas (
    id         serial PRIMARY KEY,
    subject_id int NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    name       varchar(255) NOT NULL,
    weight_pct numeric(5,2) CHECK (weight_pct >= 0 AND weight_pct <= 100),
    UNIQUE (subject_id, name)
);

CREATE TABLE IF NOT EXISTS topics (
    id              serial PRIMARY KEY,
    grade_id        int NOT NULL REFERENCES grades(id) ON DELETE RESTRICT,
    subject_id      int NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    name            varchar(255) NOT NULL,
    term            int CHECK (term BETWEEN 1 AND 4),
    content_area_id int REFERENCES content_areas(id) ON DELETE SET NULL,
    duration_hours  numeric(4,1),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (grade_id, subject_id, name)
);
CREATE INDEX IF NOT EXISTS idx_topics_grade_id ON topics(grade_id);
CREATE INDEX IF NOT EXISTS idx_topics_subject_id ON topics(subject_id);

-- Past-paper excerpts (document_sections) can now be tagged to a topic and
-- carry their own embedding, so rag.py can pull a topic-relevant excerpt the
-- same way it already pulls caps_chunks -- added here (after `topics`
-- exists) rather than on the CREATE TABLE above, which runs earlier in this
-- script, before `topics` does.
ALTER TABLE document_sections ADD COLUMN IF NOT EXISTS topic_id int REFERENCES topics(id) ON DELETE SET NULL;
ALTER TABLE document_sections ADD COLUMN IF NOT EXISTS embedding vector({dim});
CREATE INDEX IF NOT EXISTS idx_document_sections_topic_id ON document_sections(topic_id);

CREATE TABLE IF NOT EXISTS subtopics (
    id       serial PRIMARY KEY,
    topic_id int NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    name     varchar(255) NOT NULL,
    UNIQUE (topic_id, name)
);
CREATE INDEX IF NOT EXISTS idx_subtopics_topic_id ON subtopics(topic_id);

CREATE TABLE IF NOT EXISTS learning_objectives (
    id                 serial PRIMARY KEY,
    objective_code     varchar(100) UNIQUE,
    grade_id           int NOT NULL REFERENCES grades(id) ON DELETE RESTRICT,
    subject_id         int NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    topic_id           int NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
    subtopic_id        int REFERENCES subtopics(id) ON DELETE SET NULL,
    objective          text NOT NULL,
    term               int CHECK (term BETWEEN 1 AND 4),
    source_document_id int REFERENCES documents(id) ON DELETE SET NULL,
    source_page        int,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lo_grade_id ON learning_objectives(grade_id);
CREATE INDEX IF NOT EXISTS idx_lo_subject_id ON learning_objectives(subject_id);
CREATE INDEX IF NOT EXISTS idx_lo_topic_id ON learning_objectives(topic_id);
CREATE INDEX IF NOT EXISTS idx_lo_subtopic_id ON learning_objectives(subtopic_id);
CREATE INDEX IF NOT EXISTS idx_lo_source_document_id ON learning_objectives(source_document_id);

CREATE TABLE IF NOT EXISTS skills (
    id                    serial PRIMARY KEY,
    learning_objective_id int NOT NULL REFERENCES learning_objectives(id) ON DELETE CASCADE,
    skill                 text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_learning_objective_id ON skills(learning_objective_id);

CREATE TABLE IF NOT EXISTS atp_schedules (
    id                    serial PRIMARY KEY,
    learning_objective_id int NOT NULL REFERENCES learning_objectives(id) ON DELETE CASCADE,
    term                  int NOT NULL CHECK (term BETWEEN 1 AND 4),
    week                  int NOT NULL CHECK (week BETWEEN 1 AND 12),
    assessment_type       varchar(100)
);
CREATE INDEX IF NOT EXISTS idx_atp_learning_objective_id ON atp_schedules(learning_objective_id);
CREATE INDEX IF NOT EXISTS idx_atp_term_week ON atp_schedules(term, week);

-- Assessment structure (CAPS Amendments Table 4.1/4.2).
CREATE TABLE IF NOT EXISTS assessment_structure (
    id                      serial PRIMARY KEY,
    subject_id              int NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    term                    int NOT NULL CHECK (term BETWEEN 1 AND 4),
    task_type               varchar(50) NOT NULL
        CHECK (task_type IN ('assignment','test','investigation','project',
                              'june_exam','end_of_year_exam')),
    sequence_in_term        int NOT NULL DEFAULT 1,
    paper_count             int NOT NULL DEFAULT 1,
    weight_pct_of_term      numeric(5,2) CHECK (weight_pct_of_term BETWEEN 0 AND 100),
    weight_pct_of_sba       numeric(5,2) CHECK (weight_pct_of_sba BETWEEN 0 AND 100),
    -- NULL for end_of_year_exam: that task IS the 60% exam component, not part of the 40% SBA
    marking_method          varchar(50) CHECK (marking_method IN ('memo','rubric','memo_or_rubric')),
    time_allocation_minutes int,
    source_document_id      int REFERENCES documents(id) ON DELETE SET NULL,
    source_page             int,
    -- NULL = applies to every grade of the subject's phase (Senior Phase:
    -- one task structure for Gr 7-9). FET rows set it, because the Grade 12
    -- programme of assessment differs from Grades 10-11 (CAPS FET s.4).
    grade_id                int REFERENCES grades(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_assessment_structure_subject_term ON assessment_structure(subject_id, term);
-- Uniqueness now includes grade_id (NULLS NOT DISTINCT, Postgres 15+, so a
-- Senior Phase row with grade_id NULL still upserts cleanly). Databases
-- created before Grades 9-12 were added carry the old 4-column UNIQUE and
-- no grade_id column: add the column, drop the old constraint, add the new.
ALTER TABLE assessment_structure ADD COLUMN IF NOT EXISTS grade_id int REFERENCES grades(id) ON DELETE CASCADE;
DO $$
DECLARE old_name text;
BEGIN
    SELECT conname INTO old_name FROM pg_constraint
     WHERE conrelid = 'assessment_structure'::regclass AND contype = 'u'
       AND conname <> 'assessment_structure_grade_task_key'
       AND array_length(conkey, 1) = 4;
    IF old_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE assessment_structure DROP CONSTRAINT %I', old_name);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'assessment_structure_grade_task_key') THEN
        ALTER TABLE assessment_structure ADD CONSTRAINT assessment_structure_grade_task_key
            UNIQUE NULLS NOT DISTINCT (subject_id, grade_id, term, task_type, sequence_in_term);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS assessment_task_marks (
    id                       serial PRIMARY KEY,
    assessment_structure_id int NOT NULL REFERENCES assessment_structure(id) ON DELETE CASCADE,
    grade_id                int NOT NULL REFERENCES grades(id) ON DELETE CASCADE,
    paper_number             int,
    min_marks                int NOT NULL
);
-- Single-paper tasks store paper_number NULL. A plain UNIQUE treats NULLs as
-- distinct, so every re-run of load_curriculum duplicated those rows. Replace
-- it with a NULLS NOT DISTINCT constraint (after removing any duplicates).
DO $$
DECLARE old_name text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'assessment_task_marks_paper_key') THEN
        SELECT conname INTO old_name FROM pg_constraint
         WHERE conrelid = 'assessment_task_marks'::regclass AND contype = 'u';
        IF old_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE assessment_task_marks DROP CONSTRAINT %I', old_name);
        END IF;
        DELETE FROM assessment_task_marks a USING assessment_task_marks b
         WHERE a.id > b.id
           AND a.assessment_structure_id = b.assessment_structure_id
           AND a.grade_id = b.grade_id
           AND a.paper_number IS NOT DISTINCT FROM b.paper_number;
        ALTER TABLE assessment_task_marks ADD CONSTRAINT assessment_task_marks_paper_key
            UNIQUE NULLS NOT DISTINCT (assessment_structure_id, grade_id, paper_number);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS cognitive_level_weights (
    id         serial PRIMARY KEY,
    subject_id int NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    level_name varchar(50) NOT NULL
        CHECK (level_name IN ('knowledge','routine_procedures','complex_procedures','problem_solving')),
    weight_pct numeric(5,2) CHECK (weight_pct BETWEEN 0 AND 100),
    UNIQUE (subject_id, level_name)
);

-- Grades 9-12 (added 2026-10, see seed/load_curriculum.py) ----------------
-- A CAPS topic can be taught in more than one term (Grade 8 Algebraic
-- Equations: Terms 1, 2 and 4), but topics is UNIQUE per grade+subject+name.
-- `term` stays the first term taught; `terms` lists all of them and
-- `term_hours` maps term -> hours, e.g. {{"1": 3, "2": 3, "4": 3}}.
ALTER TABLE topics ADD COLUMN IF NOT EXISTS terms int[];
ALTER TABLE topics ADD COLUMN IF NOT EXISTS term_hours jsonb;
CREATE INDEX IF NOT EXISTS idx_topics_terms ON topics USING gin (terms);

-- Content-area weighting differs by grade (Senior Phase Gr 8: 25/30/25/10/10,
-- Gr 9: 15/35/30/10/10; FET: share of the Paper 1 + Paper 2 marks), but
-- content_areas is per subject and the Senior Phase subject spans Gr 7-9.
-- Per-grade weights live here; content_areas.weight_pct is legacy (Gr 8).
CREATE TABLE IF NOT EXISTS content_area_weights (
    id              serial PRIMARY KEY,
    content_area_id int NOT NULL REFERENCES content_areas(id) ON DELETE CASCADE,
    grade_id        int NOT NULL REFERENCES grades(id) ON DELETE CASCADE,
    weight_pct      numeric(5,2) NOT NULL CHECK (weight_pct BETWEEN 0 AND 100),
    exam_paper      int CHECK (exam_paper IN (1, 2)),   -- FET only
    exam_marks      int,                                -- FET only, CAPS +/-3
    UNIQUE (content_area_id, grade_id)
);
CREATE INDEX IF NOT EXISTS idx_content_area_weights_grade ON content_area_weights(grade_id);

-- Annual Teaching Plan schedule at topic level (atp_schedules above is keyed
-- to learning objectives, of which only a handful exist). ATPs change every
-- year, so each row carries the ATP's own year label ('2026', '2023/24').
-- `hours` is for the whole ATP block; a block covering several CAPS topics
-- (Grade 8 'Data Handling') is stored once per topic with topics_in_block.
CREATE TABLE IF NOT EXISTS atp_topic_schedule (
    id              serial PRIMARY KEY,
    grade_id        int NOT NULL REFERENCES grades(id) ON DELETE CASCADE,
    subject_id      int NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    year_label      varchar(20) NOT NULL,
    term            int NOT NULL CHECK (term BETWEEN 1 AND 4),
    week_start      int CHECK (week_start BETWEEN 1 AND 12),
    week_end        int CHECK (week_end BETWEEN 1 AND 12),
    hours           numeric(4,1),
    kind            varchar(20) NOT NULL
        CHECK (kind IN ('topic','assessment','revision','exam','admin')),
    label           text NOT NULL,
    topic_id        int REFERENCES topics(id) ON DELETE CASCADE,
    topics_in_block int NOT NULL DEFAULT 1,
    source_page     int
);
CREATE INDEX IF NOT EXISTS idx_atp_topic_schedule_lookup
    ON atp_topic_schedule(grade_id, year_label, term);

-- Mastery + attempts, keyed to learners(id) -- see the household-model
-- note above `learners` for why this replaced the earlier phone-keyed
-- design (tutobuddy-household-account-model-phase1-plan.md).
CREATE TABLE IF NOT EXISTS learner_topic_mastery (
    id            serial PRIMARY KEY,
    learner_id    int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    topic_id      int NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    mastery_score numeric(5,2) NOT NULL CHECK (mastery_score BETWEEN 0 AND 100),
    band          varchar(20) GENERATED ALWAYS AS (
                      CASE
                          WHEN mastery_score < 40 THEN 'remediate'
                          WHEN mastery_score < 70 THEN 'practice'
                          WHEN mastery_score < 85 THEN 'challenge'
                          ELSE 'advance'
                      END
                  ) STORED,
    last_assessed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (learner_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_learner_topic_mastery_learner ON learner_topic_mastery(learner_id);

CREATE TABLE IF NOT EXISTS learner_assessment_attempts (
    id                      serial PRIMARY KEY,
    learner_id              int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    assessment_structure_id int NOT NULL REFERENCES assessment_structure(id) ON DELETE RESTRICT,
    score_pct               numeric(5,2) NOT NULL CHECK (score_pct BETWEEN 0 AND 100),
    attempted_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_learner_attempts_learner ON learner_assessment_attempts(learner_id);

-- Ad-hoc WhatsApp "quiz me" practice attempts -- distinct from
-- learner_assessment_attempts above (which is tied to formal CAPS
-- assessment_structure tasks: assignments/tests/exams). This is what
-- closes the mastery loop: every graded practice answer here also
-- upserts learner_topic_mastery (see app.tutor.rag.record_practice_attempt).
-- Deliberately NOT FK'd to assessment_structure -- a practice question is
-- generated ad-hoc by the LLM, not a real gazetted assessment task.
CREATE TABLE IF NOT EXISTS learner_practice_attempts (
    id             serial PRIMARY KEY,
    learner_id     int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    topic_id       int NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    question       text NOT NULL,
    model_answer   text,
    learner_answer text NOT NULL,
    correctness    varchar(20) NOT NULL
        CHECK (correctness IN ('correct', 'partial', 'incorrect')),
    mastery_delta  numeric(5,2) NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_learner_practice_attempts_learner ON learner_practice_attempts(learner_id);

-- conversation_log is phone-scoped (a whole household's chat stream);
-- learner_id attributes a row to whichever learner was active when it was
-- sent. Nullable: onboarding messages predate any learner existing.
ALTER TABLE conversation_log ADD COLUMN IF NOT EXISTS learner_id int REFERENCES learners(id) ON DELETE SET NULL;

-- Safeguarding (child-safety architecture layer 4: a human reviews every
-- risk-flagged case -- the AI is never the final authority). Deliberately
-- NOT a FK to learners(id) ON DELETE CASCADE: a POPIA "DELETE" request
-- wipes the learner's profile/history, but a safeguarding record (a
-- disclosed crisis/abuse flag) is a duty-of-care/legal record that must
-- survive that deletion -- this is the one table in the schema that is
-- intentionally exempt from the right-to-deletion cascade. `phone` here is
-- a plain snapshot value, not a live reference.
CREATE TABLE IF NOT EXISTS safeguarding_flags (
    id              serial PRIMARY KEY,
    phone           text NOT NULL,
    category        text NOT NULL,
    message_excerpt text NOT NULL,
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'resolved')),
    notified_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    reviewed_at     timestamptz,
    reviewed_by     text,
    notes           text
);
CREATE INDEX IF NOT EXISTS idx_safeguarding_flags_status ON safeguarding_flags(status);

-- learner_id SNAPSHOT for cross-reference, deliberately not FK'd --
-- same reason phone isn't (see the comment on this table above): a
-- duty-of-care record must survive learner deletion.
ALTER TABLE safeguarding_flags ADD COLUMN IF NOT EXISTS learner_id int;

-- ── Memory + pedagogy (moeketsi/memory-pedagogy; spec: "Katlego memory +
-- pedagogy spec v0.1") ─────────────────────────────────────────────────────
-- Placeholder LOs: a topic with no real CAPS learning objective yet gets one
-- "<topic>.00" objective so LO-level mastery works everywhere. Real LOs
-- replace it as they are loaded; learner_events keeps the raw evidence, so
-- history can be recomputed onto them.
ALTER TABLE learning_objectives ADD COLUMN IF NOT EXISTS is_placeholder boolean NOT NULL DEFAULT false;
-- CAPS-derived LOs (seed/load_learning_objectives.py): where each came from
-- and whether a teacher still needs to check its wording.
ALTER TABLE learning_objectives ADD COLUMN IF NOT EXISTS subtopic_label text;
ALTER TABLE learning_objectives ADD COLUMN IF NOT EXISTS lo_kind varchar(10) NOT NULL DEFAULT 'new';
ALTER TABLE learning_objectives ADD COLUMN IF NOT EXISTS source_ref text;
ALTER TABLE learning_objectives ADD COLUMN IF NOT EXISTS needs_review boolean NOT NULL DEFAULT false;

-- Raw evidence, append-only. Mastery is a function of this table, so a new
-- mastery formula can always be replayed over history.
CREATE TABLE IF NOT EXISTS learner_events (
    id                 bigserial PRIMARY KEY,
    learner_id         int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    topic_id           int NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    lo_id              int REFERENCES learning_objectives(id) ON DELETE SET NULL,
    source             varchar(12) NOT NULL CHECK (source IN ('chat', 'quiz', 'photo', 'diagnostic')),
    evidence           varchar(20) NOT NULL,
    hint_level         smallint NOT NULL DEFAULT 0,
    strategy           varchar(40),
    misconception_code varchar(40),
    weight             numeric(4,3) NOT NULL,
    mastery_before     numeric(5,2),
    mastery_after      numeric(5,2),
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_learner_events_learner ON learner_events(learner_id, created_at);

-- Current estimate per learning objective (rolled up into
-- learner_topic_mastery, which PROGRESS and quiz topic-picking already read).
CREATE TABLE IF NOT EXISTS learner_lo_mastery (
    learner_id     int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    lo_id          int NOT NULL REFERENCES learning_objectives(id) ON DELETE CASCADE,
    mastery_score  numeric(5,2) NOT NULL CHECK (mastery_score BETWEEN 0 AND 100),
    evidence_count int NOT NULL DEFAULT 0,
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    next_review_at timestamptz,
    PRIMARY KEY (learner_id, lo_id)
);

-- What works for whom: Beta-Bernoulli counts per learner x topic x strategy
-- (app/tutor/pedagogy.py samples from these).
CREATE TABLE IF NOT EXISTS learner_strategy_stats (
    learner_id int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    topic_id   int NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    strategy   varchar(40) NOT NULL,
    tries      int NOT NULL DEFAULT 0,
    successes  int NOT NULL DEFAULT 0,
    PRIMARY KEY (learner_id, topic_id, strategy)
);

-- CPA + TMU (spec "Katlego CPA + mastery switching v0.1"): the level the
-- learner worked at and the TMU strand each piece of evidence speaks to.
ALTER TABLE learner_events ADD COLUMN IF NOT EXISTS cpa_level varchar(10);
ALTER TABLE learner_events ADD COLUMN IF NOT EXISTS strand varchar(30);

-- What works for whom, per CPA level (app/tutor/representation.py).
CREATE TABLE IF NOT EXISTS learner_level_stats (
    learner_id int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    topic_id   int NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    cpa_level  varchar(10) NOT NULL,
    tries      int NOT NULL DEFAULT 0,
    successes  int NOT NULL DEFAULT 0,
    PRIMARY KEY (learner_id, topic_id, cpa_level)
);

-- The evidence log: every switch the engine makes, why, and what happened
-- over the next 2 turns. chosen_by = 'random' marks the 10% exploration
-- share, so we can show the engine's pick beats chance.
-- Sign-up check-in (app/tutor/diagnostic.py): one row per completed
-- check-in. The first is the learner's baseline; later ones (CHECK-IN
-- again) are end-lines for the pilot's learning-gain measure.
CREATE TABLE IF NOT EXISTS diagnostic_results (
    id            bigserial PRIMARY KEY,
    learner_id    int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    grade         smallint NOT NULL,
    bank_version  varchar(20) NOT NULL,
    started_at    timestamptz,
    finished_at   timestamptz NOT NULL DEFAULT now(),
    score_pct     numeric(5,2) NOT NULL,
    first_try     smallint NOT NULL,
    topics        jsonb NOT NULL,
    focus         jsonb NOT NULL,
    answers       jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnostic_results_learner ON diagnostic_results(learner_id, finished_at);

-- Past papers marked against the memo (app/tutor/papers.py).
CREATE TABLE IF NOT EXISTS paper_attempts (
    id           bigserial PRIMARY KEY,
    learner_id   int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    paper_id     varchar(60),
    label        varchar(120) NOT NULL,
    squad_code   varchar(8),
    awarded      int NOT NULL,
    out_of       int NOT NULL,
    results      jsonb NOT NULL,
    finished_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_paper_attempts_learner ON paper_attempts(learner_id, finished_at);

-- Study squads: learners in one grade who do the same paper and see a
-- shared scoreboard (nicknames and marks only).
CREATE TABLE IF NOT EXISTS squads (
    code             varchar(8) PRIMARY KEY,
    grade            smallint NOT NULL,
    host_learner_id  int REFERENCES learners(id) ON DELETE SET NULL,
    paper_id         varchar(60),
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS squad_members (
    squad_code  varchar(8) NOT NULL REFERENCES squads(code) ON DELETE CASCADE,
    learner_id  int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    joined_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (squad_code, learner_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_squad_members_learner ON squad_members(learner_id);

-- Tests a learner told Katlego about (app/tutor/test_prep.py).
CREATE TABLE IF NOT EXISTS learner_tests (
    id          bigserial PRIMARY KEY,
    learner_id  int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    due_on      date,
    topics      jsonb NOT NULL DEFAULT '[]',
    note        text,
    source      varchar(12) NOT NULL DEFAULT 'learner',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_learner_tests_learner ON learner_tests(learner_id, created_at);

CREATE TABLE IF NOT EXISTS pedagogy_decisions (
    id              bigserial PRIMARY KEY,
    learner_id      int NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    topic_id        int REFERENCES topics(id) ON DELETE SET NULL,
    problem         text,
    session_turn    int,
    trigger         varchar(20) NOT NULL,
    switch          varchar(20) NOT NULL,
    strategy        varchar(40) NOT NULL,
    cpa_level       varchar(10),
    chosen_by       varchar(10) NOT NULL DEFAULT 'engine',
    mastery_at      numeric(5,2),
    no_progress     int,
    outcome         varchar(20),
    turns_to_outcome int,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pedagogy_decisions_learner ON pedagogy_decisions(learner_id, created_at);

-- Misconception taxonomy (seeded, small). topic_id NULL = applies to any
-- topic (e.g. sign errors).
CREATE TABLE IF NOT EXISTS misconceptions (
    code        varchar(40) PRIMARY KEY,
    topic_id    int REFERENCES topics(id) ON DELETE CASCADE,
    description text NOT NULL
);

-- Cross-session memory: the code-built digest of earlier work (no LLM).
-- Erased with the learner row.
ALTER TABLE learners ADD COLUMN IF NOT EXISTS memory_digest text;

-- Per-call token + cost ledger for live traffic (app/adapters/ledger.py):
-- the same telemetry fields the bake-off captures in memory, persisted.
-- Stub rows are estimates (chars/4). learner_id is a plain value, erased
-- with the learner by session.delete_active_learner.
CREATE TABLE IF NOT EXISTS llm_calls (
    id                bigserial PRIMARY KEY,
    learner_id        int,
    call              varchar(40) NOT NULL,
    provider          varchar(20) NOT NULL,
    model             varchar(80) NOT NULL,
    prompt_version    varchar(30),
    prompt_tokens     int,
    completion_tokens int,
    reasoning_tokens  int,
    estimated         boolean NOT NULL DEFAULT false,
    latency_ms        int,
    cost_usd          numeric(12,8),
    billed            boolean NOT NULL DEFAULT false,
    finish_reason     varchar(30),
    host              varchar(40),
    strategy          varchar(40),
    state_valid       boolean,
    created_at        timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS reasoning_tokens int;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS billed boolean NOT NULL DEFAULT false;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS finish_reason varchar(30);
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS host varchar(40);
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS output_mode varchar(30);
-- Prompt caching (5 Nov 2026): what the provider served from cache, and
-- how much of this prompt matched the learner's previous one (estimate).
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS cached_tokens int;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS cache_write_tokens int;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS prompt_chars int;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS shared_chars int;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS layout varchar(10);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at);

-- Starter misconception list: cross-topic, common in Senior Phase and FET
-- algebra/number work. Teachers extend it per topic (topic_id set).
INSERT INTO misconceptions (code, topic_id, description) VALUES
    ('SIGN_ERR', NULL, 'Sign error with negative numbers'),
    ('ONE_SIDE_OP', NULL, 'Applies an operation to one side of an equation only'),
    ('UNLIKE_TERMS', NULL, 'Combines unlike terms (e.g. 2x + 3 = 5x)'),
    ('PARTIAL_DISTRIB', NULL, 'Multiplies only the first term inside brackets'),
    ('ORDER_OPS', NULL, 'Ignores the order of operations'),
    ('EXP_AS_MULT', NULL, 'Treats an exponent as multiplication (3^2 = 6)'),
    ('FRAC_ADD_ACROSS', NULL, 'Adds numerators and denominators separately'),
    ('PLACE_VALUE', NULL, 'Place-value or decimal-point error'),
    ('UNITS', NULL, 'Missing or wrong units'),
    ('MISREAD', NULL, 'Answers a different question than the one asked')
ON CONFLICT (code) DO NOTHING;
"""


SCHEMA_LOCK = 72_317_001  # pg advisory lock id: one schema run at a time across processes


async def ensure_schema() -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        # Gateway, worker and bench processes can boot at the same moment;
        # concurrent CREATE/ALTER runs deadlocked (DeadlockDetectedError in
        # the 31 Oct bake-off). The advisory lock serialises them.
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", SCHEMA_LOCK)
            await conn.execute(SCHEMA.format(dim=settings.embedding_dim))
    finally:
        await conn.close()


_init_lock: asyncio.Lock | None = None
_init_loop = None


async def get_pool() -> asyncpg.Pool:
    """The shared pool. The schema check runs once per process at start-up,
    not once per concurrent first caller: before, several calls starting
    together each ran ensure_schema() and the cost ledger lost rows to
    deadlocks."""
    global _pool, _init_lock, _init_loop
    if _pool is not None:
        return _pool
    loop = asyncio.get_running_loop()
    if _init_lock is None or _init_loop is not loop:  # tests run one loop per case
        _init_lock, _init_loop = asyncio.Lock(), loop
    async with _init_lock:
        if _pool is None:
            await ensure_schema()
            _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    return _pool


def vector_literal(vec: list[float]) -> str:
    """pgvector text representation; cast with ::vector in SQL."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
