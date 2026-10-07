"""Tutor engine: retrieve grounded context, then reply Socratically —
plus term-progress reporting and practice-question generation, both grounded
in learner_topic_mastery / topics (see app.tutor.rag)."""

import datetime

from app.adapters import llm
from app.tutor import prompts
from app.tutor.rag import (
    get_past_paper_excerpts,
    get_term_progress,
    grade_scoped_context,
    pick_practice_topic,
    record_practice_attempt,
    retrieve,
)

DEFAULT_SUBJECT = "Mathematics"


async def tutor_reply(question: str, grade: int) -> str:
    """`grade` is the active learner's profile grade. Only that grade's CAPS
    extracts reach the model; see the grade rule in
    app.tutor.rag.grade_scoped_context."""
    ctx = await grade_scoped_context(question, grade)
    return await llm.socratic_reply(
        question, ctx["chunks"], grade, above=ctx["above"], grade_topics=ctx["grade_topics"],
    )


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
) -> tuple[str, dict | None]:
    """Picks the learner's weakest/least-assessed topic this term (heavily-
    weighted-and-weak first, see rag.get_term_progress), pulls past-paper
    excerpts for style/topic reference only, and has the LLM write and solve
    an original practice question — never quoting the OCR'd excerpts as
    ground truth (see prompts.practice_system).

    Returns (reply_text, pending) where `pending` is what the caller
    (app.worker.handle_active) must stash on the session so the learner's
    NEXT message can be recognised as their answer and graded — see
    grade_practice_reply below. `pending` is None when no question was set
    (e.g. no topics loaded for this grade/term yet)."""
    resolved_term = term or current_term()
    progress = await get_term_progress(learner_id, grade, resolved_term, subject)
    topic = await pick_practice_topic(progress)
    if topic is None:
        return (
            f"I don't have Term {resolved_term} {subject} topics loaded for "
            f"Grade {grade} yet 📚 Ask me a question instead and we'll work "
            f"through it together.",
            None,
        )
    excerpts = await get_past_paper_excerpts(topic["topic"], grade)
    result = await llm.practice_question(topic["topic"], grade, topic.get("band"), excerpts)
    pending = {
        "topic_id": topic["topic_id"],
        "topic": topic["topic"],
        "question": result["question"],
        "model_answer": result.get("model_answer"),
        "grade": grade,
    }
    return result["question"], pending


async def grade_practice_reply(learner_id: int, pending: dict, learner_answer: str) -> str:
    """Grades the learner's answer to the practice question stashed in
    `pending` (session.data["pending_practice"] — see app.worker), updates
    learner_topic_mastery, logs the attempt, and returns the feedback
    message. This is the write side of the mastery loop that was missing
    (see tutobuddy-pedagogy-mastery-pace-step.md's "known gaps")."""
    result = await llm.grade_practice_answer(
        pending["question"], pending.get("model_answer"), learner_answer, pending["grade"]
    )
    await record_practice_attempt(
        learner_id,
        pending["topic_id"],
        pending["question"],
        pending.get("model_answer"),
        learner_answer,
        result["correctness"],
    )
    return prompts.practice_feedback_message(result["correctness"], result["feedback"])
