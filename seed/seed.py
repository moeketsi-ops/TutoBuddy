"""Seed the CAPS corpus + NSC-style question bank.

    docker compose run --rm seed

POC scope: ~18 hand-authored curriculum chunks and 10 questions. The real
content pipeline (blueprint §5) bulk-ingests DBE CAPS/ATP documents and past
papers — deliberately out of scope here. No textbook content (copyright).
"""

import asyncio
import json
from pathlib import Path

from app.adapters.embeddings import embed
from app.cognitive_levels import normalize as normalize_cognitive_level
from app.db import ensure_schema, get_pool, vector_literal

HERE = Path(__file__).parent


async def main() -> None:
    await ensure_schema()
    chunks = json.loads((HERE / "caps_chunks.json").read_text())
    questions = json.loads((HERE / "question_bank.json").read_text())

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE caps_chunks, question_bank RESTART IDENTITY")

        for c in chunks:
            vec = vector_literal(await embed(f"{c['topic']}. {c['content']}"))
            await conn.execute(
                """
                INSERT INTO caps_chunks (grade, subject, term, topic, doc_type, content, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
                """,
                c["grade"], c["subject"], c["term"], c["topic"],
                c["doc_type"], c["content"], vec,
            )

        for q in questions:
            await conn.execute(
                """
                INSERT INTO question_bank
                    (grade, subject, topic, question, memo_answer, marks, cognitive_level, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                q["grade"], q["subject"], q["topic"], q["question"],
                q["memo_answer"], q["marks"],
                normalize_cognitive_level(q.get("cognitive_level")), q["source"],
            )

    print(f"Seeded {len(chunks)} CAPS chunks and {len(questions)} question-bank items.")


if __name__ == "__main__":
    asyncio.run(main())
