"""RAG-grounded Socratic tutoring over the seeded CAPS corpus."""


def test_homework_question_gets_grounded_socratic_reply(onboarded_chat):
    onboarded_chat.send_text("How do I factorise x squared plus 5x plus 6?")
    reply = onboarded_chat.wait_for_reply()
    # Grounded in the retrieved CAPS chunk...
    assert "factoris" in reply.lower()
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
    # The corpus has no content at grade <= 8, so no grounded topic may appear.
    assert "Grade 12" not in reply


def test_smalltalk_does_not_trigger_the_tutor_engine(onboarded_chat):
    onboarded_chat.send_text("hi")
    reply = onboarded_chat.wait_for_reply()
    assert "question" in reply.lower()


def test_help_command(onboarded_chat):
    onboarded_chat.send_text("HELP")
    reply = onboarded_chat.wait_for_reply()
    assert "DELETE" in reply and "RESET" in reply
