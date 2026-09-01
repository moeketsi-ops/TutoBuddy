"""RAG over the seeded CAPS corpus (Postgres + pgvector).

Metadata filters apply BEFORE similarity search — a Grade 9 question must
never retrieve Grade 12 content (blueprint §5.3). Lower-grade prerequisite
material is allowed (grade <= learner grade).
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
