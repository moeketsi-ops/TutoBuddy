"""Grade 8-12 curriculum load (seed/load_curriculum.py): database-level
checks, no chat involved. Requires
`docker compose run --rm seed python -m seed.load_curriculum` to have run.

Each expectation below is a fact from the DBE source documents, not a
snapshot of whatever the loader happened to write:
  - CAPS Senior Phase Gr 7-9: 150 teaching hours per grade (s.3.2), 22 topics
  - CAPS FET Gr 10-12: 4.5 h/week; exam papers 100+100 (Gr 10), 150+150 (Gr 11-12)
"""

import asyncio
import os

import asyncpg

EXPECTED_TOPICS = {8: 22, 9: 22, 10: 13, 11: 12, 12: 12}
TEACHING_HOURS = {8: 150, 9: 150, 10: 139.5, 11: 144, 12: 112.5}
PAPER_MARKS = {10: 100, 11: 150, 12: 150}


def _q(sql: str, *args):
    async def run():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()
    return asyncio.run(run())


def test_topic_counts_and_teaching_hours_per_grade():
    rows = _q(
        "SELECT g.grade_number AS g, count(*) AS n, sum(t.duration_hours) AS h "
        "FROM topics t JOIN grades g ON g.id = t.grade_id "
        "JOIN subjects s ON s.id = t.subject_id AND lower(s.name) = 'mathematics' "
        "GROUP BY g.grade_number")
    got = {r["g"]: (r["n"], float(r["h"])) for r in rows}
    for g, n in EXPECTED_TOPICS.items():
        assert got.get(g, (0, 0))[0] == n, (g, got.get(g))
        assert abs(got[g][1] - TEACHING_HOURS[g]) < 0.01, (g, got[g])


def test_every_term_has_topics_in_every_grade():
    rows = _q(
        "SELECT g.grade_number AS g, array_agg(DISTINCT x) AS terms "
        "FROM topics t JOIN grades g ON g.id = t.grade_id, unnest(t.terms) x "
        "GROUP BY g.grade_number")
    got = {r["g"]: sorted(r["terms"]) for r in rows}
    for g in (8, 9):
        assert got[g] == [1, 2, 3, 4], (g, got[g])
    for g in (10, 11, 12):   # FET Term 4 is revision + exams only for some grades
        assert set(got[g]) >= {1, 2, 3}, (g, got[g])


def test_grade8_multi_term_topic_and_pythagoras():
    rows = _q(
        "SELECT t.name, t.terms FROM topics t JOIN grades g ON g.id = t.grade_id "
        "WHERE g.grade_number = 8 AND t.name IN ('Algebraic Equations', 'Theorem of Pythagoras')")
    got = {r["name"]: sorted(r["terms"]) for r in rows}
    assert got == {"Algebraic Equations": [1, 2, 4], "Theorem of Pythagoras": [3]}, got


def test_content_area_weights_sum_to_100_per_grade():
    rows = _q(
        "SELECT g.grade_number AS g, sum(w.weight_pct) AS total "
        "FROM content_area_weights w JOIN grades g ON g.id = w.grade_id GROUP BY g.grade_number")
    got = {r["g"]: float(r["total"]) for r in rows}
    for g in (8, 9, 10, 11, 12):
        assert abs(got[g] - 100) <= 0.05, (g, got.get(g))


def test_fet_exam_marks_per_paper_match_caps():
    rows = _q(
        "SELECT g.grade_number AS g, w.exam_paper AS p, sum(w.exam_marks) AS m "
        "FROM content_area_weights w JOIN grades g ON g.id = w.grade_id "
        "WHERE w.exam_paper IS NOT NULL GROUP BY 1, 2")
    for r in rows:
        assert r["m"] == PAPER_MARKS[r["g"]], dict(r)
    assert len(rows) == 6


def test_fet_assessment_rows_and_no_trial_exam():
    rows = _q(
        "SELECT g.grade_number AS g, sum(a.weight_pct_of_sba) AS sba, "
        "count(*) FILTER (WHERE a.task_type = 'end_of_year_exam') AS exams "
        "FROM assessment_structure a JOIN grades g ON g.id = a.grade_id GROUP BY 1")
    got = {r["g"]: (float(r["sba"]), r["exams"]) for r in rows}
    assert got[10] == (100.0, 1) and got[11] == (100.0, 1), got
    # Grade 12: the 25% Trial Examination is deliberately not loaded.
    assert got[12] == (75.0, 1), got


def test_senior_phase_assessment_not_duplicated_on_reload():
    rows = _q(
        "SELECT assessment_structure_id, grade_id, paper_number, count(*) AS n "
        "FROM assessment_task_marks GROUP BY 1, 2, 3 HAVING count(*) > 1")
    assert rows == [], [dict(r) for r in rows]


def test_atp_rows_loaded_with_year_labels_and_topics():
    rows = _q(
        "SELECT g.grade_number AS g, a.year_label AS y, "
        "count(*) FILTER (WHERE a.kind = 'topic' AND a.topic_id IS NULL) AS orphan, "
        "count(*) FILTER (WHERE a.kind = 'topic') AS topics "
        "FROM atp_topic_schedule a JOIN grades g ON g.id = a.grade_id GROUP BY 1, 2")
    got = {r["g"]: (r["y"], r["orphan"], r["topics"]) for r in rows}
    assert got[8][0] == "2026" and got[9][0] == "2026", got
    for g in (10, 11, 12):
        assert got[g][0] == "2023/24", got
    for g, (_, orphan, topics) in got.items():
        assert orphan == 0 and topics > 0, (g, got[g])
