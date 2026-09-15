"""Load the CAPS curriculum-engine data into Katlego's Postgres:
Grade 8 Mathematics (phases/grades/subjects/content areas/topics/
learning objectives/skills) plus the Senior Phase Mathematics
assessment weighting (Table 4.1/4.2 of the GET CAPS Amendments doc,
grades 7-9: SBA task structure, per-grade mark totals, cognitive-level
split).

    docker compose run --rm seed python -m seed.load_curriculum

Source data: seed/curriculum/grade8_mathematics.json, copied in from
the founder's standalone curriculum-engine repo. The assessment-model
seed values below are ported from that repo's
database/migration_learner_assessment_model.sql (a DO $$ block written
against a differently-shaped, id-keyed `learners` table there -- not
reused here, see app/db.py for why).

Scope: "database merge only" (founder decision, 2026-09). This script
does not touch app/tutor/rag.py, app/orchestrator/session.py or
app/orchestrator/safety.py, and inserts no learner_topic_mastery or
learner_assessment_attempts rows -- those tables exist (see
app/db.py) but stay empty until the tutor loop is wired to write to
them, a separate follow-up.

Idempotent: every insert is an upsert (ON CONFLICT ... DO UPDATE /
DO NOTHING) keyed on the same unique constraints app/db.py defines, so
re-running this after editing grade8_mathematics.json is safe and
won't duplicate rows. Uses upserts rather than seed.py's
TRUNCATE-then-insert pattern because these tables have downstream FKs
(topics -> learning_objectives -> skills, assessment_structure ->
assessment_task_marks) that a TRUNCATE would cascade-delete.
"""

import asyncio
import json
from pathlib import Path

from app.db import ensure_schema, get_pool

HERE = Path(__file__).parent
CURRICULUM_JSON = HERE / "curriculum" / "grade8_mathematics.json"

SENIOR_PHASE = "Senior Phase"
SUBJECT = "Mathematics"

# (term, task_type, sequence_in_term, paper_count, weight_pct_of_term,
#  weight_pct_of_sba, marking_method, time_allocation_minutes, source_page,
#  {grade_number: [(paper_number_or_None, min_marks), ...]})
ASSESSMENT_TASKS = [
    (1, "assignment", 1, 1, 40, 8, "memo", None, 64,
     {7: [(None, 50)], 8: [(None, 50)], 9: [(None, 50)]}),
    (1, "test", 2, 1, 60, 6, "memo", 60, 64,
     {7: [(None, 40)], 8: [(None, 50)], 9: [(None, 50)]}),
    (2, "investigation", 1, 1, 40, 6, "memo_or_rubric", None, 64,
     {7: [(None, 40)], 8: [(None, 40)], 9: [(None, 50)]}),
    (2, "june_exam", 2, 2, 60, 8, "memo", 90, 64,
     {7: [(1, 50), (2, 50)], 8: [(1, 60), (2, 60)], 9: [(1, 75), (2, 75)]}),
    (3, "project", 1, 1, 40, 6, "rubric", None, 64,
     {7: [(None, 50)], 8: [(None, 50)], 9: [(None, 50)]}),
    (3, "test", 2, 1, 60, 6, "memo", 60, 64,
     {7: [(None, 40)], 8: [(None, 50)], 9: [(None, 50)]}),
    (4, "end_of_year_exam", 1, 2, 100, None, "memo", 90, 64,
     {7: [(1, 50), (2, 50)], 8: [(1, 60), (2, 60)], 9: [(1, 75), (2, 75)]}),
]

COGNITIVE_WEIGHTS = [
    ("knowledge", 25),
    ("routine_procedures", 45),
    ("complex_procedures", 20),
    ("problem_solving", 10),
]


async def _ensure_reference_rows(conn) -> tuple[int, dict[int, int]]:
    """Create Senior Phase / Grades 7-9 / Mathematics if missing.
    Returns (subject_id, {grade_number: grade_id})."""
    phase_id = await conn.fetchval(
        "INSERT INTO phases (name) VALUES ($1) "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        SENIOR_PHASE,
    )
    grade_ids: dict[int, int] = {}
    for gn in (7, 8, 9):
        grade_ids[gn] = await conn.fetchval(
            "INSERT INTO grades (phase_id, grade_number) VALUES ($1, $2) "
            "ON CONFLICT (phase_id, grade_number) DO UPDATE SET grade_number = EXCLUDED.grade_number "
            "RETURNING id",
            phase_id, gn,
        )
    subject_id = await conn.fetchval(
        "INSERT INTO subjects (name, phase_id) VALUES ($1, $2) "
        "ON CONFLICT (name, phase_id) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        SUBJECT, phase_id,
    )
    return subject_id, grade_ids


async def _load_topics(conn, subject_id: int, grade_id: int, data: dict) -> None:
    content_area_ids: dict[str, int] = {}
    for ca in data["content_areas"]:
        content_area_ids[ca["name"]] = await conn.fetchval(
            "INSERT INTO content_areas (subject_id, name, weight_pct) VALUES ($1, $2, $3) "
            "ON CONFLICT (subject_id, name) DO UPDATE SET weight_pct = EXCLUDED.weight_pct "
            "RETURNING id",
            subject_id, ca["name"], ca["weight_pct"],
        )

    for t in data["topics"]:
        topic_id = await conn.fetchval(
            "INSERT INTO topics (grade_id, subject_id, name, term, duration_hours, content_area_id) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (grade_id, subject_id, name) DO UPDATE SET "
            "term = EXCLUDED.term, duration_hours = EXCLUDED.duration_hours, "
            "content_area_id = EXCLUDED.content_area_id "
            "RETURNING id",
            grade_id, subject_id, t["name"], t["term"], t["duration_hours"],
            content_area_ids[t["content_area"]],
        )
        for lo in t.get("learning_objectives", []):
            lo_id = await conn.fetchval(
                "INSERT INTO learning_objectives "
                "(objective_code, grade_id, subject_id, topic_id, objective, source_page) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (objective_code) DO UPDATE SET objective = EXCLUDED.objective "
                "RETURNING id",
                lo["objective_code"], grade_id, subject_id, topic_id,
                lo["objective"], lo.get("source_page"),
            )
            for skill in lo.get("skills", []):
                exists = await conn.fetchval(
                    "SELECT 1 FROM skills WHERE learning_objective_id = $1 AND skill = $2",
                    lo_id, skill,
                )
                if not exists:
                    await conn.execute(
                        "INSERT INTO skills (learning_objective_id, skill) VALUES ($1, $2)",
                        lo_id, skill,
                    )


async def _load_assessment_model(conn, subject_id: int, grade_ids: dict[int, int]) -> None:
    for level, pct in COGNITIVE_WEIGHTS:
        await conn.execute(
            "INSERT INTO cognitive_level_weights (subject_id, level_name, weight_pct) "
            "VALUES ($1, $2, $3) ON CONFLICT (subject_id, level_name) DO NOTHING",
            subject_id, level, pct,
        )

    for (term, task_type, seq, papers, pct_term, pct_sba, method,
         minutes, page, marks) in ASSESSMENT_TASKS:
        task_id = await conn.fetchval(
            "INSERT INTO assessment_structure "
            "(subject_id, term, task_type, sequence_in_term, paper_count, "
            " weight_pct_of_term, weight_pct_of_sba, marking_method, "
            " time_allocation_minutes, source_page) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
            "ON CONFLICT (subject_id, term, task_type, sequence_in_term) "
            "DO UPDATE SET weight_pct_of_term = EXCLUDED.weight_pct_of_term "
            "RETURNING id",
            subject_id, term, task_type, seq, papers, pct_term, pct_sba,
            method, minutes, page,
        )
        for gn, paper_marks in marks.items():
            for paper_number, min_marks in paper_marks:
                await conn.execute(
                    "INSERT INTO assessment_task_marks "
                    "(assessment_structure_id, grade_id, paper_number, min_marks) "
                    "VALUES ($1,$2,$3,$4) "
                    "ON CONFLICT (assessment_structure_id, grade_id, paper_number) "
                    "DO UPDATE SET min_marks = EXCLUDED.min_marks",
                    task_id, grade_ids[gn], paper_number, min_marks,
                )


async def main() -> None:
    await ensure_schema()
    data = json.loads(CURRICULUM_JSON.read_text())
    assert data["grade"] == 8 and data["subject"].lower() == "mathematics"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            subject_id, grade_ids = await _ensure_reference_rows(conn)
            await _load_topics(conn, subject_id, grade_ids[8], data)
            await _load_assessment_model(conn, subject_id, grade_ids)

    n_topics = len(data["topics"])
    n_lo = sum(len(t.get("learning_objectives", [])) for t in data["topics"])
    print(
        f"Loaded {n_topics} Grade 8 Mathematics topics ({n_lo} with real "
        f"learning objectives) + Senior Phase assessment structure for "
        f"grades 7-9."
    )


if __name__ == "__main__":
    asyncio.run(main())
