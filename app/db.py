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
    cognitive_level text,
    source text
);

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
    UNIQUE (subject_id, term, task_type, sequence_in_term)
);
CREATE INDEX IF NOT EXISTS idx_assessment_structure_subject_term ON assessment_structure(subject_id, term);

CREATE TABLE IF NOT EXISTS assessment_task_marks (
    id                       serial PRIMARY KEY,
    assessment_structure_id int NOT NULL REFERENCES assessment_structure(id) ON DELETE CASCADE,
    grade_id                int NOT NULL REFERENCES grades(id) ON DELETE CASCADE,
    paper_number             int,
    min_marks                int NOT NULL,
    UNIQUE (assessment_structure_id, grade_id, paper_number)
);

CREATE TABLE IF NOT EXISTS cognitive_level_weights (
    id         serial PRIMARY KEY,
    subject_id int NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    level_name varchar(50) NOT NULL
        CHECK (level_name IN ('knowledge','routine_procedures','complex_procedures','problem_solving')),
    weight_pct numeric(5,2) CHECK (weight_pct BETWEEN 0 AND 100),
    UNIQUE (subject_id, level_name)
);

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
"""


async def ensure_schema() -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(SCHEMA.format(dim=settings.embedding_dim))
    finally:
        await conn.close()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        await ensure_schema()
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    return _pool


def vector_literal(vec: list[float]) -> str:
    """pgvector text representation; cast with ::vector in SQL."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
