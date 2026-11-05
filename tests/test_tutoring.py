"""RAG-grounded Socratic tutoring over the seeded CAPS corpus."""

from tests.conftest import REAL_LLM, WORKER_ERROR, assert_tutored, run_with_app_db


def test_homework_question_gets_grounded_socratic_reply(onboarded_chat):
    onboarded_chat.send_text("How do I factorise x squared plus 5x plus 6?")
    reply = onboarded_chat.wait_for_reply()
    if REAL_LLM:
        # A real model may coach without repeating the word "factorise"
        # (e.g. "two numbers that multiply to 6 and add to 5").
        assert_tutored(reply)
    else:
        # Grade rule: this learner's profile is Grade 11, so the reply is
        # grounded in a Grade 11 CAPS note only (factorising trinomials is a
        # Grade 10 note, which a Grade 11 learner no longer gets)...
        assert "Grade 11" in reply, reply
        # ...and Socratic: coaches rather than closing the conversation.
        assert "?" in reply


def test_grade_filter_never_retrieves_above_learner_grade(chat):
    # Grade 8 learner asks about a Grade 12-only topic.
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text("AGREE")
    chat.wait_for_reply()  # name prompt
    chat.send_text("Grade8Learner")
    chat.wait_for_reply()  # grade prompt
    chat.send_text("8")
    chat.wait_for_reply()  # welcome
    chat.send_text("How do I differentiate from first principles?")
    reply = chat.wait_for_reply()
    assert WORKER_ERROR not in reply.lower(), reply
    # Grade rule: a higher-grade topic may be NAMED (brief preview), never
    # taught -- the Grade 12 first-principles formula must not appear.
    assert "f(x + h)" not in reply, reply
    if not REAL_LLM:
        # Stub: told it's another grade's topic, redirected to this term's
        # Grade 8 focus (from the ATP / CAPS term topics).
        assert "Grade 12" in reply and "Grade 8" in reply, reply
        assert "This term in Grade 8" in reply, reply


def test_grade_scoped_context_follows_the_grade_rule():
    """Grade rule (founder, 2026-10-07), checked at the retrieval layer, LLM
    independent: the model only ever gets CAPS extracts from the learner's own
    grade, a higher-grade concept is flagged by grade + topic name only, and
    the learner's grade topic list comes from the curriculum."""
    from app.tutor.rag import first_taught_above, grade_scoped_context

    questions = ("How do I differentiate from first principles?",
                 "How do I collect like terms?", "How do I add fractions?",
                 "What is the theorem of Pythagoras?")

    async def run():
        return {(g, q): await grade_scoped_context(q, g) for g in (8, 10, 12) for q in questions}

    for (grade, q), ctx in run_with_app_db(run).items():
        assert all(c["grade"] == grade for c in ctx["chunks"]), (grade, q, ctx["chunks"])
        assert ctx["grade_topics"], grade  # needs seed.load_curriculum
        if ctx["above"]:
            assert ctx["above"]["grade"] > grade and set(ctx["above"]) == {"grade", "topic"}

    assert first_taught_above("How do I differentiate from first principles?", 8)["grade"] == 12
    assert first_taught_above("explain the sine rule", 10)["grade"] == 11
    assert first_taught_above("explain the sine rule", 11) is None   # own grade: taught normally
    assert first_taught_above("What is the theorem of Pythagoras?", 8) is None
    assert first_taught_above("How do I add fractions?", 10) is None


def test_smalltalk_does_not_trigger_the_tutor_engine(onboarded_chat):
    onboarded_chat.send_text("hi")
    reply = onboarded_chat.wait_for_reply()
    assert "question" in reply.lower()


def test_thanks_mid_chat_gets_a_short_close_not_the_greeting():
    from app.worker import SMALLTALK_MID_CHAT, SMALLTALK_REPLY, smalltalk_reply
    assert smalltalk_reply({"turns": []}) == SMALLTALK_REPLY
    assert smalltalk_reply({"turns": [{"at": 1000.0}]}, now=1000.0 + 60) == SMALLTALK_MID_CHAT
    assert smalltalk_reply({"turns": [{"at": 1000.0}]}, now=1000.0 + 3 * 3600) == SMALLTALK_REPLY


def test_help_command(onboarded_chat):
    onboarded_chat.send_text("HELP")
    reply = onboarded_chat.wait_for_reply()
    assert "DELETE" in reply and "RESET" in reply
