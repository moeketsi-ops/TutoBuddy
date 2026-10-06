"""Load the CAPS Mathematics curriculum for Grades 8-12 into Katlego's
Postgres: phases/grades/subjects, content areas (with per-grade weights),
topics (with every term each is taught in), learning objectives/skills, the
assessment model, and the Annual Teaching Plan (ATP) schedule.

    docker compose run --rm seed python -m seed.load_curriculum

Source data (all built from DBE documents, see each file's "source" field):
  seed/curriculum/grade{8..12}_mathematics.json
      Grade 8/9: CAPS Senior Phase Mathematics Gr 7-9, "Time allocation per
      Term" tables (CAPS p.74 / p.118) and content-area weighting (p.11).
      Grade 8 was rebuilt 2026-10 from the real Grade 8 table: the earlier
      file carried the Grade 7 term plan and had no Theorem of Pythagoras.
      Topic names and the 5 hand-transcribed learning objectives are kept
      verbatim, so caps_chunks notes and past-paper tagging still match.
      Grades 10-12: CAPS FET Mathematics Gr 10-12, s.3.2.1 time allocation
      (p.16), s.2.5 exam weighting (p.10), s.4 programme of assessment (p.54).
  seed/curriculum/atp/grade{8..12}_mathematics_atp.json
      Week-by-week ATP schedules. Grades 8-9: 2026 ATPs. Grades 10-12: the
      2023/24 DBE ATPs (not confirmed as this year's plan), stored under
      their own year label so nothing presents them as the 2026 schedule.

Senior Phase assessment weighting (Grades 7-9, GET CAPS Amendments Table
4.1/4.2) is unchanged from the original Grade 8 loader and applies to every
Senior Phase grade (assessment_structure.grade_id NULL). FET rows are per
grade because Grade 12's programme of assessment differs from Grades 10-11.

Grade 12 Trial Examination: deliberately NOT loaded (founder decision
2026-10-06, no trial_exam task type). The JSON records it under
assessment.skipped_tasks and this script prints it, so the gap stays visible:
the trial is 25% of the Grade 12 school-based assessment mark.

Idempotent: curriculum rows are upserts keyed on app/db.py's unique
constraints; ATP rows for a (grade, subject, year_label) are replaced
wholesale (no other table references them).
"""

import asyncio
import json
from pathlib import Path

from app.db import ensure_schema, get_pool

HERE = Path(__file__).parent
CURRICULUM_DIR = HERE / "curriculum"
ATP_DIR = CURRICULUM_DIR / "atp"
GRADES = (8, 9, 10, 11, 12)
SUBJECT = "Mathematics"
PHASE_GRADES = {"Senior Phase": (7, 8, 9), "FET Phase": (10, 11, 12)}

# ── Senior Phase assessment model (GET CAPS Amendments, Table 4.1/4.2) ──────
# (term, task_type, sequence_in_term, paper_count, weight_pct_of_term,
#  weight_pct_of_sba, marking_method, time_allocation_minutes, source_page,
#  {grade_number: [(paper_number_or_None, min_marks), ...]})
SENIOR_PHASE_TASKS = [
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
SENIOR_PHASE_COGNITIVE = [
    ("knowledge", 25), ("routine_procedures", 45),
    ("complex_procedures", 20), ("problem_solving", 10),
]

UPSERT_TASK = (
    "INSERT INTO assessment_structure "
    "(subject_id, grade_id, term, task_type, sequence_in_term, paper_count, "
    " weight_pct_of_term, weight_pct_of_sba, marking_method, "
    " time_allocation_minutes, source_page) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) "
    "ON CONFLICT ON CONSTRAINT assessment_structure_grade_task_key DO UPDATE SET "
    "paper_count = EXCLUDED.paper_count, weight_pct_of_term = EXCLUDED.weight_pct_of_term, "
    "weight_pct_of_sba = EXCLUDED.weight_pct_of_sba, marking_method = EXCLUDED.marking_method, "
    "time_allocation_minutes = EXCLUDED.time_allocation_minutes, source_page = EXCLUDED.source_page "
    "RETURNING id"
)
UPSERT_MARKS = (
    "INSERT INTO assessment_task_marks (assessment_structure_id, grade_id, paper_number, min_marks) "
    "VALUES ($1,$2,$3,$4) "
    "ON CONFLICT ON CONSTRAINT assessment_task_marks_paper_key "
    "DO UPDATE SET min_marks = EXCLUDED.min_marks"
)


async def _reference_rows(conn) -> tuple[dict[str, int], dict[int, int]]:
    """Phases, Grades 7-12 and one Mathematics subject per phase.
    Returns ({phase_name: subject_id}, {grade_number: grade_id})."""
    subject_ids, grade_ids = {}, {}
    for phase, grades in PHASE_GRADES.items():
        phase_id = await conn.fetchval(
            "INSERT INTO phases (name) VALUES ($1) "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id", phase)
        for gn in grades:
            grade_ids[gn] = await conn.fetchval(
                "INSERT INTO grades (phase_id, grade_number) VALUES ($1, $2) "
                "ON CONFLICT (phase_id, grade_number) DO UPDATE SET grade_number = EXCLUDED.grade_number "
                "RETURNING id", phase_id, gn)
        subject_ids[phase] = await conn.fetchval(
            "INSERT INTO subjects (name, phase_id) VALUES ($1, $2) "
            "ON CONFLICT (name, phase_id) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            SUBJECT, phase_id)
    return subject_ids, grade_ids


async def _load_grade(conn, subject_id: int, grade_id: int, data: dict) -> dict[str, int]:
    """Content areas + per-grade weights, topics, learning objectives.
    Returns {topic_name: topic_id}."""
    area_ids: dict[str, int] = {}
    for ca in data["content_areas"]:
        # content_areas.weight_pct is left as-is (legacy, Grade 8 era); the
        # per-grade figure goes to content_area_weights.
        area_ids[ca["name"]] = await conn.fetchval(
            "INSERT INTO content_areas (subject_id, name) VALUES ($1, $2) "
            "ON CONFLICT (subject_id, name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            subject_id, ca["name"])
        await conn.execute(
            "INSERT INTO content_area_weights (content_area_id, grade_id, weight_pct, exam_paper, exam_marks) "
            "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (content_area_id, grade_id) DO UPDATE SET "
            "weight_pct = EXCLUDED.weight_pct, exam_paper = EXCLUDED.exam_paper, exam_marks = EXCLUDED.exam_marks",
            area_ids[ca["name"]], grade_id, ca["weight_pct"], ca.get("exam_paper"), ca.get("exam_marks"))

    topic_ids: dict[str, int] = {}
    for t in data["topics"]:
        topic_id = await conn.fetchval(
            "INSERT INTO topics (grade_id, subject_id, name, term, terms, term_hours, duration_hours, content_area_id) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8) "
            "ON CONFLICT (grade_id, subject_id, name) DO UPDATE SET "
            "term = EXCLUDED.term, terms = EXCLUDED.terms, term_hours = EXCLUDED.term_hours, "
            "duration_hours = EXCLUDED.duration_hours, content_area_id = EXCLUDED.content_area_id "
            "RETURNING id",
            grade_id, subject_id, t["name"], t["term"], t.get("terms") or [t["term"]],
            json.dumps(t.get("term_hours") or {}), t["duration_hours"], area_ids[t["content_area"]])
        topic_ids[t["name"]] = topic_id
        for lo in t.get("learning_objectives", []):
            lo_id = await conn.fetchval(
                "INSERT INTO learning_objectives "
                "(objective_code, grade_id, subject_id, topic_id, objective, source_page) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (objective_code) DO UPDATE SET objective = EXCLUDED.objective, "
                "topic_id = EXCLUDED.topic_id RETURNING id",
                lo["objective_code"], grade_id, subject_id, topic_id, lo["objective"], lo.get("source_page"))
            for skill in lo.get("skills", []):
                exists = await conn.fetchval(
                    "SELECT 1 FROM skills WHERE learning_objective_id = $1 AND skill = $2", lo_id, skill)
                if not exists:
                    await conn.execute(
                        "INSERT INTO skills (learning_objective_id, skill) VALUES ($1, $2)", lo_id, skill)
    return topic_ids


async def _senior_phase_assessment(conn, subject_id: int, grade_ids: dict[int, int]) -> None:
    for level, pct in SENIOR_PHASE_COGNITIVE:
        await conn.execute(
            "INSERT INTO cognitive_level_weights (subject_id, level_name, weight_pct) VALUES ($1,$2,$3) "
            "ON CONFLICT (subject_id, level_name) DO UPDATE SET weight_pct = EXCLUDED.weight_pct",
            subject_id, level, pct)
    for (term, task_type, seq, papers, pct_term, pct_sba, method, minutes, page, marks) in SENIOR_PHASE_TASKS:
        task_id = await conn.fetchval(UPSERT_TASK, subject_id, None, term, task_type, seq, papers,
                                      pct_term, pct_sba, method, minutes, page)
        for gn, paper_marks in marks.items():
            for paper_number, min_marks in paper_marks:
                await conn.execute(UPSERT_MARKS, task_id, grade_ids[gn], paper_number, min_marks)


async def _fet_assessment(conn, subject_id: int, grade_id: int, data: dict) -> list[str]:
    a = data["assessment"]
    for level, pct in a["cognitive_levels"].items():
        await conn.execute(
            "INSERT INTO cognitive_level_weights (subject_id, level_name, weight_pct) VALUES ($1,$2,$3) "
            "ON CONFLICT (subject_id, level_name) DO UPDATE SET weight_pct = EXCLUDED.weight_pct",
            subject_id, level, pct)
    for task in a["sba_tasks"]:
        await conn.fetchval(UPSERT_TASK, subject_id, grade_id, task["term"], task["task_type"],
                            task["sequence_in_term"], 2 if task["task_type"] == "june_exam" else 1,
                            None, task["weight_pct_of_sba"], None, None, 54)
    exam = a["end_of_year_exam"]
    exam_id = await conn.fetchval(UPSERT_TASK, subject_id, grade_id, 4, "end_of_year_exam", 1,
                                  exam["papers"], 100, None, "memo", exam["minutes_per_paper"], 54)
    for paper in range(1, exam["papers"] + 1):
        await conn.execute(UPSERT_MARKS, exam_id, grade_id, paper, exam["marks_per_paper"])
    return [f"Grade {data['grade']} Term {s['term']} {s['task']} ({s['weight_pct_of_sba']}% of SBA): "
            f"skipped, {s['reason']}" for s in a.get("skipped_tasks", [])]


async def _load_atp(conn, subject_id: int, grade_id: int, topic_ids: dict[str, int], atp: dict) -> int:
    await conn.execute(
        "DELETE FROM atp_topic_schedule WHERE grade_id = $1 AND subject_id = $2 AND year_label = $3",
        grade_id, subject_id, atp["year_label"])
    n = 0
    for e in atp["entries"]:
        targets = [topic_ids[name] for name in e["topics"]] or [None]
        for topic_id in targets:
            await conn.execute(
                "INSERT INTO atp_topic_schedule (grade_id, subject_id, year_label, term, week_start, week_end, "
                "hours, kind, label, topic_id, topics_in_block, source_page) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
                grade_id, subject_id, atp["year_label"], e["term"], e["week_start"], e["week_end"],
                e["hours"], e["kind"], e["label"], topic_id, max(1, len(e["topics"])), e.get("source_page"))
            n += 1
    return n


async def main() -> None:
    await ensure_schema()
    files = {g: json.loads((CURRICULUM_DIR / f"grade{g}_mathematics.json").read_text()) for g in GRADES}
    atps = {g: json.loads(p.read_text()) for g in GRADES
            if (p := ATP_DIR / f"grade{g}_mathematics_atp.json").exists()}
    for g, d in files.items():
        assert d["grade"] == g and d["subject"].lower() == "mathematics", g

    report, notes = [], []
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            subject_ids, grade_ids = await _reference_rows(conn)
            await _senior_phase_assessment(conn, subject_ids["Senior Phase"], grade_ids)
            for g, d in files.items():
                subject_id = subject_ids[d["phase"]]
                topic_ids = await _load_grade(conn, subject_id, grade_ids[g], d)
                if d["phase"] == "FET Phase":
                    notes += await _fet_assessment(conn, subject_id, grade_ids[g], d)
                n_atp = 0
                if g in atps:
                    n_atp = await _load_atp(conn, subject_id, grade_ids[g], topic_ids, atps[g])
                n_lo = sum(len(t.get("learning_objectives", [])) for t in d["topics"])
                atp_label = f"ATP {atps[g]['year_label']}: {n_atp} rows" if g in atps else "no ATP"
                report.append(f"  Grade {g:>2}: {len(d['topics'])} topics, {n_lo} learning objectives, {atp_label}")

    print("Loaded CAPS Mathematics (Senior Phase + FET assessment model):")
    print("\n".join(report))
    for n in notes:
        print("  NOTE", n)


if __name__ == "__main__":
    asyncio.run(main())
