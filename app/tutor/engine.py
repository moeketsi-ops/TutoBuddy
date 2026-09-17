"""Tutor engine: retrieve grounded context, then reply Socratically —
plus term-progress reporting and practice-question generation, both grounded
in learner_topic_mastery / topics (see app.tutor.rag)."""

import datetime

from app.adapters import llm
from app.tutor import prompts
from app.tutor.rag import (
    get_past_paper_excerpts,
    get_term_progress,
    pick_practice_topic,
    retrieve,
)

DEFAULT_SUBJECT = "Mathematics"


async def tutor_reply(question: str, grade: int) -> str:
    chunks = await retrieve(question, grade)
    return await llm.socratic_reply(question, chunks, grade)


async def eval_answer(question: str, grade: int) -> str:
    """Direct worked answer for the eval harness (never sent to learners)."""
    chunks = await retrieve(question, grade)
    return await llm.direct_answer(question, chunks, grade)


def current_term() -> int:
    """South African school-year term from today's date — a rough calendar
    mapping (Term 1 Jan-Mar, Term 2 Apr-Jun, Term 3 Jul-Sep, Term 4 Oct-Dec),
    not the real gazetted term dates (which shift year to year). Good enough
    until real ATP dates (atp_schedules) are loaded; callers can always pass
    an explicit term instead."""
    month = datetime.date.today().month
    return min(4, (month - 1) // 3 + 1)


async def progress_reply(
    learner_id: int, grade: int, term: int | None = None, subject: str = DEFAULT_SUBJECT
) -> str:
    """Term-progress message for the learner. Pure data formatting under the
    hood (prompts.progress_message) — no LLM call, so nothing here can be
    hallucinated. `learner_id` identifies the individual learner within a
    household (see tutobuddy-household-account-model-phase1-plan.md), not
    a phone number -- a phone may have several learners behind it."""
    progress = await get_term_progress(learner_id, grade, term or current_term(), subject)
    return prompts.progress_message(progress)


async def practice_reply(
    learner_id: int, grade: int, term: int | None = None, subject: str = DEFAULT_SUBJECT
) -> str:
    """Picks the learner's weakest/least-assessed topic this term (heavily-
    weighted-and-weak first, see rag.get_term_progress), pulls past-paper
    excerpts for style/topic reference only, and has the LLM write and solve
    an original practice question — never quoting the OCR'd excerpts as
    ground truth (see prompts.practice_system)."""
    resolved_term = term or current_term()
    progress = await get_term_progress(learner_id, grade, resolved_term, subject)
    topic = await pick_practice_topic(progress)
    if topic is None:
        return (
            f"I don't have Term {resolved_term} {subject} topics loaded for "
            f"Grade {grade} yet 📚 Ask me a question instead and we'll work "
            f"through it together."
        )
    excerpts = await get_past_paper_excerpts(topic["topic"], grade)
    return await llm.practice_question(topic["topic"], grade, topic.get("band"), excerpts)
