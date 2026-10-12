"""RAG over the seeded CAPS corpus (Postgres + pgvector), plus term-level
mastery/progress lookups and past-paper practice retrieval.

Metadata filters apply BEFORE similarity search — a Grade 9 question must
never retrieve Grade 12 content (blueprint §5.3). Lower-grade prerequisite
material is allowed (grade <= learner grade).

The second half of this module reads from the curriculum-engine merge (see
project doc tutobuddy-database-merge-decision.md):
  - `topics` / `learner_topic_mastery` — structured curriculum + mastery,
    used for term progress and picking what to practise next.
  - `document_sections` (document_type 'past_paper' or 'marking_memo') — OCR'd real exam
    papers, loaded by seed/load_past_papers.py.

IMPORTANT about past papers: the OCR pass is known to garble maths notation
(fractions, exponents, multi-step arithmetic — see
tutobuddy-past-papers-ocr-pipeline.md, e.g. "3-(-3)+8" came out as
"3---3+8-1-7+12+1"). Every excerpt returned below carries verified=False.
Nothing from get_past_paper_excerpts() should ever be treated as a fact —
see prompts.practice_system() for how the LLM is instructed to use these
excerpts (style/topic reference only, to write and solve an original
question, never to copy a number from them).
"""

import datetime

from app.adapters.embeddings import embed
from app.db import get_pool, vector_literal


async def retrieve(question: str, grade: int, subject: str | None = None, k: int = 3) -> list[dict]:
    vec = vector_literal(await embed(question))
    pool = await get_pool()
    async with pool.acquire() as conn:
        if subject:
            rows = await conn.fetch(
                """
                SELECT grade, subject, term, topic, doc_type, content,
                       embedding <=> $1::vector AS distance
                FROM caps_chunks
                WHERE grade <= $2 AND subject = $3
                ORDER BY distance
                LIMIT $4
                """,
                vec, grade, subject, k,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT grade, subject, term, topic, doc_type, content,
                       embedding <=> $1::vector AS distance
                FROM caps_chunks
                WHERE grade <= $2
                ORDER BY distance
                LIMIT $3
                """,
                vec, grade, k,
            )
    return [dict(r) for r in rows]


# ── Term-topic mastery / progress ────────────────────────────────────────────

async def _grade_id(conn, grade: int) -> int | None:
    """Grade numbers are unique in practice (one phase per grade band: 7-9
    Senior Phase, 10-12 FET), so the first match is taken without also
    joining on phase."""
    return await conn.fetchval(
        "SELECT id FROM grades WHERE grade_number = $1 LIMIT 1", grade
    )


# ── Grade rule (founder, 2026-10-07) ────────────────────────────────────────
# A learner is taught ONLY their own grade's CAPS methods, notation and
# strategies -- the grade comes from the ACTIVE LEARNER'S PROFILE
# (learners.grade, mirrored in the session), never a default. Never a higher
# grade's method. A missing earlier-grade skill may be revised briefly,
# labelled as revision and explained the Grade-N way. A question about a
# higher-grade topic gets at most a two-sentence preview (no method) and a
# redirect to the learner's own grade.
#
# Enforced in code here (what the model is given) and in
# prompts.socratic_system (how it may use it):
#   chunks       -- CAPS extracts from the learner's own grade only (not
#                   "<= grade": no earlier-grade method to drift into)
#   above        -- grade + topic name when the question uses a concept CAPS
#                   first teaches in a HIGHER grade (deterministic table
#                   below); never that grade's content
#   grade_topics -- the learner's grade topic list (seed/load_curriculum)
#
# Why a keyword table and not embedding distance: with the offline hash
# embedder, "nearest chunk is a higher grade" misfired in testing (Grade 8
# "theorem of Pythagoras" matched a Grade 11 statistics chunk). The table
# only lists concepts whose first CAPS grade is unambiguous.

_FIRST_TAUGHT = (
    # (grade first taught in CAPS Mathematics, topic, keywords)
    (12, "Differential calculus", ("derivative", "differentiat", "first principles", "calculus")),
    (12, "Exponential and logarithmic functions", ("logarithm", "log base")),
    (12, "Trigonometry - compound angles", ("compound angle", "double angle")),
    (12, "Patterns, sequences and series", ("sigma notation", "arithmetic series", "geometric series")),
    (11, "Trigonometry (sine, area, cosine rules)", ("sine rule", "cosine rule", "area rule")),
    (11, "Equations and inequalities", ("quadratic formula", "completing the square")),
    (10, "Trigonometry", ("trigonometr", "sine of", "cosine of", "tangent ratio", "sin(", "cos(", "tan(")),
)


def first_taught_above(question: str, grade: int) -> dict | None:
    """{grade, topic} if the question uses a concept CAPS first teaches above
    `grade` (highest such grade wins), else None."""
    q = question.lower()
    for first_grade, topic, keywords in _FIRST_TAUGHT:  # ordered high -> low
        if first_grade > grade and any(k in q for k in keywords):
            return {"grade": first_grade, "topic": topic}
    return None


async def grade_scoped_context(
    question: str, grade: int, subject: str = "Mathematics", k: int = 3
) -> dict:
    vec = vector_literal(await embed(question))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT grade, subject, term, topic, doc_type, content,
                   embedding <=> $1::vector AS distance
            FROM caps_chunks
            WHERE grade = $2 AND subject = $3
            ORDER BY distance
            LIMIT $4
            """,
            vec, grade, subject, k,
        )
        topic_rows = await conn.fetch(
            "SELECT t.name FROM topics t JOIN grades g ON g.id = t.grade_id "
            "JOIN subjects s ON s.id = t.subject_id "
            "WHERE g.grade_number = $1 AND lower(s.name) = lower($2) "
            "ORDER BY t.term, t.name",
            grade, subject,
        )
    return {
        "chunks": [dict(r) for r in rows],
        "above": first_taught_above(question, grade),
        "grade_topics": [r["name"] for r in topic_rows],
    }


async def term_focus_for(learner_id: int, grade: int, term: int) -> dict | None:
    """The topic this learner should be steered back to: the top of
    get_term_progress (this term's topics for their grade, weighted-and-weak
    first) plus its first CAPS learning objective, if one is loaded."""
    progress = await get_term_progress(learner_id, grade, term)
    topic = await pick_practice_topic(progress)
    if topic is None:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        objective = await conn.fetchval(
            "SELECT objective FROM learning_objectives WHERE topic_id = $1 "
            "ORDER BY objective_code LIMIT 1",
            topic["topic_id"],
        )
    return {"term": term, "topic": topic["topic"], "objective": objective,
            "schedule_source": progress.get("schedule_source")}


async def get_term_progress(
    learner_id: int, grade: int, term: int, subject: str = "Mathematics"
) -> dict:
    """This learner's progress across the current term's topics: per-topic
    mastery (band + score, or not-yet-assessed), plus two summary numbers —
    coverage (share of topics with at least one recorded score) and the
    average mastery over those. This is the data behind the term-progress
    message the bot reports in chat (see prompts.progress_message).

    `learner_id` (not phone -- see tutobuddy-household-account-model-phase1-
    plan.md) identifies the individual learner within a household; a phone
    number may have several learners behind it.

    Topics are ranked heavily-weighted-and-weak first (same ordering as the
    reference gap-ranking query in migration_learner_assessment_model.sql),
    so pick_practice_topic() below can just take the first row.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        grade_id = await _grade_id(conn, grade)
        if grade_id is None:
            return {
                "term": term, "subject": subject, "topics": [],
                "coverage_pct": 0, "avg_mastery": None,
            }

        # Which topics count as "this term": the ATP for the current school
        # year if one is loaded for this grade (what classes are actually
        # being taught), otherwise every CAPS topic taught in this term
        # (topics.terms; a topic can span several terms). ATPs stored under
        # an older year label (e.g. the 2023/24 FET ATPs) are deliberately
        # not used here -- see seed/load_curriculum.py.
        year_label = str(datetime.date.today().year)
        use_atp = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM atp_topic_schedule a JOIN subjects s ON s.id = a.subject_id "
            "WHERE a.grade_id = $1 AND a.year_label = $2 AND lower(s.name) = lower($3))",
            grade_id, year_label, subject,
        )
        sql = """
            SELECT t.id AS topic_id, t.name AS topic, t.term,
                   ca.name AS content_area,
                   COALESCE(caw.weight_pct, ca.weight_pct) AS content_area_weight,
                   ltm.mastery_score, ltm.band
            FROM topics t
            JOIN subjects s ON s.id = t.subject_id
            LEFT JOIN content_areas ca ON ca.id = t.content_area_id
            LEFT JOIN content_area_weights caw
                   ON caw.content_area_id = ca.id AND caw.grade_id = t.grade_id
            LEFT JOIN learner_topic_mastery ltm
                   ON ltm.topic_id = t.id AND ltm.learner_id = $1
            WHERE t.grade_id = $2 AND lower(s.name) = lower($4)
              AND CASE WHEN $7::bool THEN true
                       WHEN $5::bool THEN EXISTS (
                        SELECT 1 FROM atp_topic_schedule a
                        WHERE a.topic_id = t.id AND a.term = $3
                          AND a.year_label = $6 AND a.kind = 'topic')
                       ELSE $3 = ANY(COALESCE(t.terms, ARRAY[t.term])) END
            ORDER BY COALESCE(caw.weight_pct, ca.weight_pct) DESC NULLS LAST,
                     ltm.mastery_score ASC NULLS FIRST,
                     t.name
            """
        query_args = (learner_id, grade_id, term, subject, use_atp, year_label)
        rows = await conn.fetch(sql, *query_args, False)
        revision = False
        if not rows:
            # No topics scheduled this term (e.g. Grade 12 Term 4 is revision
            # and final exams only, CAPS FET s.3.2.1): offer the whole year's
            # topics for revision rather than telling the learner nothing is
            # loaded.
            rows = await conn.fetch(sql, *query_args, True)
            revision = bool(rows)

    topics = [dict(r) for r in rows]
    assessed = [t for t in topics if t["mastery_score"] is not None]
    coverage_pct = round(100 * len(assessed) / len(topics)) if topics else 0
    avg_mastery = (
        round(sum(float(t["mastery_score"]) for t in assessed) / len(assessed), 1)
        if assessed else None
    )
    return {
        "term": term,
        "subject": subject,
        "schedule_source": ("revision: all topics" if revision
                            else f"ATP {year_label}" if use_atp else "CAPS"),
        "topics": topics,
        "coverage_pct": coverage_pct,
        "avg_mastery": avg_mastery,
    }


async def pick_practice_topic(progress: dict) -> dict | None:
    """What to practise next: get_term_progress already orders topics
    heavily-weighted-and-weak first, so the top row is the right choice."""
    topics = progress.get("topics") or []
    return topics[0] if topics else None


# ── Past-paper practice excerpts (unverified OCR — see module docstring) ────

async def get_past_paper_excerpts(topic_name: str, grade: int, k: int = 2) -> list[dict]:
    """Topic-relevant excerpts from OCR'd past papers, for practice-question
    generation. Every result has verified=False: this corpus's OCR quality
    is known-unreliable on maths notation. Callers must never present this
    content to a learner as fact — see prompts.practice_system()."""
    vec = vector_literal(await embed(topic_name))
    pool = await get_pool()
    async with pool.acquire() as conn:
        grade_id = await _grade_id(conn, grade)
        rows = await conn.fetch(
            """
            SELECT d.title, ds.page_number, ds.content,
                   ds.embedding <=> $1::vector AS distance
            FROM document_sections ds
            JOIN documents d ON d.id = ds.document_id
            WHERE d.document_type IN ('past_paper', 'marking_memo')
              AND ds.embedding IS NOT NULL
              AND (d.grade_id IS NULL OR d.grade_id = $2)
            ORDER BY distance
            LIMIT $3
            """,
            vec, grade_id, k,
        )
    return [
        {
            "title": r["title"],
            "page": r["page_number"],
            "content": r["content"],
            "verified": False,
        }
        for r in rows
    ]


# ── Closing the mastery loop: grading a practice attempt updates mastery ────

# Placeholder mastery-delta magnitudes -- a simple, transparent heuristic
# (not a calibrated learning model): a correct answer nudges mastery up
# more than a partial one costs on an incorrect answer, and a
# never-assessed topic starts at a neutral midpoint (50, which already
# lands in the 'practice' band per the <40/<70/<85 bands on
# learner_topic_mastery). Revisit once there's enough real attempt data to
# calibrate against, per tutobuddy-dynamic-pedagogy-engine-design.md
# section 9 (strategy-effectiveness tracking) and section 16 (adaptive
# intervention threshold) -- this is the foundation those build on, not a
# finished version of them.
MASTERY_BASELINE = 50.0
MASTERY_DELTA = {"correct": 12.0, "partial": 4.0, "incorrect": -6.0}


async def record_practice_attempt(
    learner_id: int,
    topic_id: int,
    question: str,
    model_answer: str | None,
    learner_answer: str,
    correctness: str,
) -> None:
    """Logs the attempt (learner_practice_attempts) and upserts
    learner_topic_mastery, clamped to [0, 100]. This is the write side that
    was missing since the progress/practice-question step shipped -- see
    tutobuddy-pedagogy-mastery-pace-step.md's "known gaps" and
    tutobuddy-dynamic-pedagogy-engine-design.md's "relationship to what's
    already built"."""
    delta = MASTERY_DELTA[correctness]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Grade rule: mastery is only ever built on the learner's OWN
            # grade's topics (profile grade == topic grade). Refuse anything
            # else rather than record progress on another grade's work.
            same_grade = await conn.fetchval(
                "SELECT g.grade_number = l.grade FROM topics t "
                "JOIN grades g ON g.id = t.grade_id, learners l "
                "WHERE t.id = $1 AND l.id = $2",
                topic_id, learner_id,
            )
            if not same_grade:
                raise ValueError(
                    f"grade rule: topic {topic_id} is not in learner {learner_id}'s grade"
                )
            await conn.execute(
                f"""
                INSERT INTO learner_topic_mastery (learner_id, topic_id, mastery_score)
                VALUES ($1, $2, GREATEST(0, LEAST(100, {MASTERY_BASELINE} + $3)))
                ON CONFLICT (learner_id, topic_id) DO UPDATE
                    SET mastery_score = GREATEST(0, LEAST(100,
                            learner_topic_mastery.mastery_score + $3)),
                        last_assessed_at = now()
                """,
                learner_id, topic_id, delta,
            )
            await conn.execute(
                """
                INSERT INTO learner_practice_attempts
                    (learner_id, topic_id, question, model_answer, learner_answer,
                     correctness, mastery_delta)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                learner_id, topic_id, question, model_answer, learner_answer,
                correctness, delta,
            )
