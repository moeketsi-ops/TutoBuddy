"""Tutor engine: retrieve grounded context, then reply Socratically."""

from app.adapters import llm
from app.tutor.rag import retrieve


async def tutor_reply(question: str, grade: int) -> str:
    chunks = await retrieve(question, grade)
    return await llm.socratic_reply(question, chunks, grade)


async def eval_answer(question: str, grade: int) -> str:
    """Direct worked answer for the eval harness (never sent to learners)."""
    chunks = await retrieve(question, grade)
    return await llm.direct_answer(question, chunks, grade)
