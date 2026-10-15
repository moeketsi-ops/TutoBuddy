"""CAPS learning objectives (seed/load_learning_objectives.py) and the
objective-based scoring that PROGRESS shows (mastery.objective_progress).

Needs seed.load_curriculum and seed.load_learning_objectives to have run."""

import asyncio
import json
import os
from pathlib import Path

import asyncpg

DB = os.environ.get("DATABASE_URL", "")
FILES = Path(__file__).resolve().parents[1] / "seed" / "curriculum" / "objectives"


def _run(coro):
    return asyncio.run(coro)


def test_every_objective_file_is_well_formed():
    for g in (8, 9, 10, 11, 12):
        data = json.loads((FILES / f"grade{g}_mathematics_objectives.json").read_text())
        codes = [lo["code"] for lo in data["objectives"]]
        assert data["grade"] == g and len(codes) == len(set(codes)), g
        assert all(c.startswith(f"ZA-MATH-G{g:02d}-") for c in codes), g
        assert all(0 < len(lo["objective"]) <= 300 for lo in data["objectives"]), g


def test_every_topic_has_real_caps_objectives():
    async def run():
        conn = await asyncpg.connect(DB)
        try:
            return await conn.fetch(
                """
                SELECT g.grade_number, t.name,
                       count(lo.id) FILTER (WHERE NOT lo.is_placeholder) AS real_los
                FROM topics t JOIN grades g ON g.id = t.grade_id
                JOIN subjects s ON s.id = t.subject_id
                LEFT JOIN learning_objectives lo ON lo.topic_id = t.id
                WHERE lower(s.name) = 'mathematics' AND g.grade_number BETWEEN 8 AND 12
                GROUP BY 1, 2
                """)
        finally:
            await conn.close()
    rows = _run(run())
    empty = [(r["grade_number"], r["name"]) for r in rows if r["real_los"] == 0]
    assert rows and not empty, empty


def test_scoring_weights_topics_by_caps_hours_and_keeps_coverage_separate():
    """Two Grade 8 Term 1 topics: Integers (9 h) mastered on one objective
    at 90, Numeric and Geometric Patterns (4.5 h) on one at 30. Understanding
    is hours-weighted: (9*90 + 4.5*30) / 13.5 = 70. Coverage counts
    objectives, weighted the same way, and is reported separately."""
    from app.tutor import mastery
    from tests.conftest import run_with_app_db

    async def run():
        from app.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            account = await conn.fetchval("INSERT INTO accounts DEFAULT VALUES RETURNING id")
            learner = await conn.fetchval(
                "INSERT INTO learners (account_id, nickname, grade) VALUES ($1, 'Score', 8) RETURNING id",
                account)
            try:
                topics = {r["name"]: r["id"] for r in await conn.fetch(
                    "SELECT t.id, t.name FROM topics t JOIN grades g ON g.id = t.grade_id "
                    "WHERE g.grade_number = 8 AND t.name IN ('Integers', 'Numeric and Geometric Patterns')")}
                for name, score in (("Integers", 90), ("Numeric and Geometric Patterns", 30)):
                    lo = (await mastery.lo_candidates(conn, topics[name]))[0]
                    await conn.execute(
                        "INSERT INTO learner_lo_mastery (learner_id, lo_id, mastery_score) VALUES ($1, $2, $3)",
                        learner, lo["id"], score)
                return await mastery.objective_progress(conn, learner, list(topics.values()), 1), topics
            finally:
                await conn.execute("DELETE FROM accounts WHERE id = $1", account)

    prog, topics = run_with_app_db(run)
    assert prog["understanding"] == 70.0
    ints, pats = prog["topics"][topics["Integers"]], prog["topics"][topics["Numeric and Geometric Patterns"]]
    assert ints["covered"] == pats["covered"] == 1
    assert prog["covered"] == 2 and prog["total"] == ints["total"] + pats["total"]
    expected = round(100 * (9 * 1 / ints["total"] + 4.5 * 1 / pats["total"]) / 13.5)
    assert prog["coverage_pct"] == expected
