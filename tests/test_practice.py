"""Closing the mastery loop: a practice-question answer gets graded and
updates learner_topic_mastery (app.tutor.rag.record_practice_attempt).

Uses a Grade 8 learner, not the Grade 11 `onboarded_chat` fixture: only
Grade 8 Mathematics is loaded (seed/load_curriculum.py), with topics in all
four terms, so current_term() always finds something to practise. Requires
`docker compose run --rm seed python -m seed.load_curriculum` to have run.
"""

from tests.conftest import AGREE


def _grade8_learner(chat) -> None:
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text(AGREE)
    chat.wait_for_reply()  # name prompt
    chat.send_text("MasteryTest")
    chat.wait_for_reply()  # grade prompt
    chat.send_text("8")
    chat.wait_for_reply()  # welcome


def test_practice_answer_is_graded_and_pending_clears(chat):
    _grade8_learner(chat)

    chat.send_text("quiz me")
    question = chat.wait_for_reply()
    assert question  # got *something* back either way

    chat.send_text("42")  # almost certainly wrong, but that's fine -- we're
    # asserting grading happened at all, not correctness of this guess.
    feedback = chat.wait_for_reply()
    assert any(icon in feedback for icon in ("✅", "➗", "❌")), feedback
    assert "another" in feedback.lower()

    # Pending cleared: the learner's next ordinary message is NOT re-graded
    # as an answer to the (already-answered) practice question.
    chat.send_text("How do I collect like terms?")
    normal_reply = chat.wait_for_reply()
    assert not any(icon in normal_reply for icon in ("✅", "➗", "❌")), normal_reply


def test_skip_clears_pending_without_grading(chat):
    _grade8_learner(chat)

    chat.send_text("quiz me")
    chat.wait_for_reply()

    chat.send_text("SKIP")
    reply = chat.wait_for_reply()
    assert "okay, skipped" in reply.lower(), reply  # not the "nothing pending" reply

    # SKIP with nothing pending says so rather than pretending to skip.
    chat.send_text("SKIP")
    reply2 = chat.wait_for_reply()
    assert "no practice question" in reply2.lower()


def test_mastery_is_only_recorded_on_the_learners_own_grade():
    """Grade rule: a Grade 8 profile can build mastery on Grade 8 topics only.
    record_practice_attempt refuses a Grade 12 topic and writes nothing."""
    import os

    import asyncpg
    import pytest

    from app.tutor.rag import record_practice_attempt

    async def run():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            account_id = await conn.fetchval("INSERT INTO accounts DEFAULT VALUES RETURNING id")
            learner_id = await conn.fetchval(
                "INSERT INTO learners (account_id, nickname, grade) VALUES ($1, 'GradeRule', 8) "
                "RETURNING id", account_id)
            topic_for = lambda g: conn.fetchval(  # noqa: E731
                "SELECT t.id FROM topics t JOIN grades g ON g.id = t.grade_id "
                "WHERE g.grade_number = $1 ORDER BY t.id LIMIT 1", g)
            own, other = await topic_for(8), await topic_for(12)
            await record_practice_attempt(learner_id, own, "q", "a", "a", "correct")
            with pytest.raises(ValueError, match="grade rule"):
                await record_practice_attempt(learner_id, other, "q", "a", "a", "correct")
            rows = await conn.fetch(
                "SELECT topic_id FROM learner_topic_mastery WHERE learner_id = $1", learner_id)
            return [r["topic_id"] for r in rows], own
        finally:
            await conn.execute("DELETE FROM accounts WHERE id = $1", account_id)
            await conn.close()

    from tests.conftest import run_with_app_db

    mastered, own = run_with_app_db(run)
    assert mastered == [own]
