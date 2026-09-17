"""POPIA consent gate + onboarding state machine."""


def test_new_learner_hits_consent_gate_first(chat):
    chat.send_text("How do I factorise x² + 5x + 6?")
    reply = chat.wait_for_reply()
    # No tutoring before guardian consent — POPIA launch blocker.
    assert "POPIA" in reply
    assert "AGREE" in reply


def test_consent_is_required_not_optional(chat):
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text("no thanks just answer my question")
    reply = chat.wait_for_reply()
    assert "AGREE" in reply  # re-prompt, no tutoring


def test_full_onboarding_flow(chat):
    chat.send_text("hello")
    assert "POPIA" in chat.wait_for_reply()
    chat.send_text("AGREE")
    assert "call you" in chat.wait_for_reply().lower()  # profile-creation name prompt
    chat.send_text("Thabo")
    assert "grade" in chat.wait_for_reply().lower()
    chat.send_text("not a grade")
    assert "8" in chat.wait_for_reply()
    chat.send_text("11")
    welcome = chat.wait_for_reply()
    assert "Grade 11" in welcome
    assert "Thabo" in welcome


def test_name_step_reprompts_on_empty_or_reserved_word(chat):
    chat.send_text("hi")
    chat.wait_for_reply()
    chat.send_text("AGREE")
    chat.wait_for_reply()
    chat.send_text("RESET")  # a command word, not a usable nickname here
    reply = chat.wait_for_reply()
    assert "didn\'t quite catch" in reply.lower() or "call you" in reply.lower()
    chat.send_text("Naledi")
    assert "grade" in chat.wait_for_reply().lower()


def test_delete_erases_data_and_restarts_onboarding(onboarded_chat):
    onboarded_chat.send_text("DELETE")
    assert "deleted" in onboarded_chat.wait_for_reply().lower()
    onboarded_chat.send_text("hi again")
    assert "POPIA" in onboarded_chat.wait_for_reply()
