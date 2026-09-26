"""Pilot grade: a Grade 8 learner gets Grade 8 CAPS-grounded tutoring."""


def test_grade8_homework_question_is_grounded_in_grade8_content(chat):
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text("AGREE")
    chat.wait_for_reply()  # name prompt
    chat.send_text("Lerato")
    chat.wait_for_reply()  # grade prompt
    chat.send_text("8")
    chat.wait_for_reply()  # welcome
    chat.send_text("How do I collect like terms in 4x - 8y + x - y?")
    reply = chat.wait_for_reply()
    assert "Grade 8" in reply, reply          # retrieval never reaches above Grade 8
    assert "couldn't find" not in reply        # and Grade 8 content actually exists
