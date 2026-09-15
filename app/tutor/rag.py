"""RAG over the seeded CAPS corpus (Postgres + pgvector), plus term-level
mastery/progress lookups and past-paper practice retrieval.

Metadata filters apply BEFORE similarity search — a Grade 9 question must
never retrieve Grade 12 content (blueprint §5.3). Lower-grade prerequisite
material is allowed (grade <= learner grade).

The second half of this module reads from the curriculum-engine merge (see
project doc tutobuddy-database-merge-decision.md):
  - `topics` / `learner_topic_mastery` — structured curriculum + mastery,
    used for term progress and picking what to practise next.
  - `document_sections` (document_type='past_paper') — OCR'd real exam
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


async def get_term_progress(
    phone: str, grade: int, term: int, subject: str = "Mathematics"
) -> dict:
    """This learner's progress across the current term's topics: per-topic
    mastery (band + score, or not-yet-assessed), plus two summary numbers —
    coverage (share of topics with at least one recorded score) and the
    average mastery over those. This is the data behind the term-progress
    message the bot reports in chat (see prompts.progress_message).

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

        rows = await conn.fetch(
            """
            SELECT t.id AS topic_id, t.name AS topic, t.term,
                   ca.name AS content_area, ca.weight_pct AS content_area_weight,
                   ltm.mastery_score, ltm.band
            FROM topics t
            JOIN subjects s ON s.id = t.subject_id
            LEFT JOIN content_areas ca ON ca.id = t.content_area_id
            LEFT JOIN learner_topic_mastery ltm
                   ON ltm.topic_id = t.id AND ltm.learner_phone = $1
            WHERE t.grade_id = $2 AND t.term = $3 AND lower(s.name) = lower($4)
            ORDER BY ca.weight_pct DESC NULLS LAST,
                     ltm.mastery_score ASC NULLS FIRST,
                     t.name
            """,
            phone, grade_id, term, subject,
        )

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
            WHERE d.document_type = 'past_paper'
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
