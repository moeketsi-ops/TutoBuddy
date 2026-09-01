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

CREATE TABLE IF NOT EXISTS learners (
    phone text PRIMARY KEY,
    display_name text,
    grade int,
    consent_given_at timestamptz,
    created_at timestamptz DEFAULT now()
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
