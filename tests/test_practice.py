"""Closing the mastery loop: a practice-question answer gets graded and
updates learner_topic_mastery (app.tutor.rag.record_practice_attempt).

Uses a Grade 8 learner, not the Grade 11 `onboarded_chat` fixture: only
Grade 8 Mathematics is loaded (seed/load_curriculum.py), with topics in all
four terms, so current_term() always finds something to practise. Requires
`docker compose run --rm seed python -m seed.load_curriculum` to have run.
"""


def _grade8_learner(chat) -> None:
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text("AGREE")
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
