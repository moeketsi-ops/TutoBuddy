"""Load CAPS learning objectives for Grade 8-12 Mathematics.

    docker compose run --rm seed python -m seed.load_learning_objectives

Source files: seed/curriculum/objectives/grade{8..12}_mathematics_objectives.json
  Grade 8/9: CAPS Senior Phase Mathematics Gr 7-9, s.2.7 "Specification of
  content (phase overview)", the Grade 8 / Grade 9 column; one LO per CAPS
  bullet ("concepts and skills").
  Grade 10-12: CAPS FET Mathematics Gr 10-12, s.3.2.3 "Topic allocation per
  term", the numbered "Curriculum statement" column; term from the page.
Extracted from the DBE PDFs (text layer), wording kept, PDF damage repaired,
each file checked against its source by a second pass. Items whose maths
notation could not be restored with certainty are loaded with
needs_review = true. A teacher review of every file is still owed.

Run AFTER seed.load_curriculum (needs the topics). Idempotent: upsert on
objective_code. Never deletes: an LO dropped from a file stays (mastery
history may point at it); the loader prints such orphans.
"""

import asyncio
import json
from pathlib import Path

import asyncpg

from app.config import settings
from app.db import ensure_schema

HERE = Path(__file__).parent / "curriculum" / "objectives"


async def load_grade(conn, path: Path) -> tuple[int, int, list[str]]:
    data = json.loads(path.read_text())
    grade = data["grade"]
    topics = {r["name"]: r for r in await conn.fetch(
        """
        SELECT t.id, t.name, t.grade_id, t.subject_id FROM topics t
        JOIN grades g ON g.id = t.grade_id JOIN subjects s ON s.id = t.subject_id
        WHERE g.grade_number = $1 AND lower(s.name) = 'mathematics'
        """, grade)}
    uncertain = set(data.get("uncertain") or [])
    loaded, missing_topics = 0, set()
    for lo in data["objectives"]:
        t = topics.get(lo["topic"])
        if t is None:
            missing_topics.add(lo["topic"])
            continue
        await conn.execute(
            """
            INSERT INTO learning_objectives
                (objective_code, grade_id, subject_id, topic_id, objective, term, source_page,
                 subtopic_label, lo_kind, source_ref, needs_review, is_placeholder)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, false)
            ON CONFLICT (objective_code) DO UPDATE SET
                topic_id = EXCLUDED.topic_id, objective = EXCLUDED.objective, term = EXCLUDED.term,
                source_page = EXCLUDED.source_page, subtopic_label = EXCLUDED.subtopic_label,
                lo_kind = EXCLUDED.lo_kind, source_ref = EXCLUDED.source_ref,
                needs_review = EXCLUDED.needs_review, is_placeholder = false
            """,
            lo["code"], t["grade_id"], t["subject_id"], t["id"], lo["objective"], lo.get("term"),
            lo.get("source_page"), lo.get("subtopic"), lo.get("kind") or "new", data.get("source"),
            lo["code"] in uncertain,
        )
        loaded += 1
    in_file = {lo["code"] for lo in data["objectives"]}
    orphans = [r["objective_code"] for r in await conn.fetch(
        """
        SELECT lo.objective_code FROM learning_objectives lo JOIN grades g ON g.id = lo.grade_id
        WHERE g.grade_number = $1 AND NOT lo.is_placeholder AND lo.source_ref IS NOT NULL
        """, grade) if r["objective_code"] not in in_file]
    no_lo = [n for n, t in topics.items() if not await conn.fetchval(
        "SELECT 1 FROM learning_objectives WHERE topic_id = $1 AND NOT is_placeholder LIMIT 1", t["id"])]
    print(f"  Grade {grade}: {loaded} objectives loaded, {len(uncertain)} flagged for review"
          + (f"; UNKNOWN topics in file: {sorted(missing_topics)}" if missing_topics else "")
          + (f"; topics still without a real LO: {no_lo}" if no_lo else "")
          + (f"; orphans kept: {orphans}" if orphans else ""))
    return loaded, len(uncertain), sorted(missing_topics)


async def main() -> None:
    await ensure_schema()
    conn = await asyncpg.connect(settings.database_url)
    try:
        total = 0
        async with conn.transaction():
            for path in sorted(HERE.glob("grade*_mathematics_objectives.json")):
                n, _, _ = await load_grade(conn, path)
                total += n
        print(f"Loaded {total} learning objectives. Topics with real LOs no longer use their "
              f"TOPIC-<id>.00 placeholder for new evidence (old evidence on it is kept).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
