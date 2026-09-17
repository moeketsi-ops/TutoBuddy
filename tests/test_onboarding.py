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


def test_delete_last_learner_keeps_household_asks_for_new_name(onboarded_chat):
    # DELETE removes the LEARNER profile, not the household/consent -- a
    # second guardian message shouldn't have to re-consent from scratch.
    onboarded_chat.send_text("DELETE")
    reply = onboarded_chat.wait_for_reply()
    assert "deleted" in reply.lower()
    assert "call you" in reply.lower()  # straight back into the name step
    onboarded_chat.send_text("Kabelo")
    assert "grade" in onboarded_chat.wait_for_reply().lower()


def test_add_learner_creates_sibling_and_switch_moves_between_them(onboarded_chat):
    # onboarded_chat is "Thabo", Grade 11.
    onboarded_chat.send_text("ADD LEARNER")
    assert "call you" in onboarded_chat.wait_for_reply().lower()
    onboarded_chat.send_text("Naledi")
    assert "grade" in onboarded_chat.wait_for_reply().lower()
    onboarded_chat.send_text("9")
    added = onboarded_chat.wait_for_reply()
    assert "Naledi" in added and "added" in added.lower()

    # Now chatting as Naledi (Grade 9) -- SWITCH should offer both siblings.
    onboarded_chat.send_text("SWITCH")
    listing = onboarded_chat.wait_for_reply()
    assert "Thabo" in listing and "Naledi" in listing

    onboarded_chat.send_text("Thabo")
    switched = onboarded_chat.wait_for_reply()
    assert "Thabo" in switched and "Grade 11" in switched


def test_switch_with_only_one_learner_says_so(onboarded_chat):
    onboarded_chat.send_text("SWITCH")
    reply = onboarded_chat.wait_for_reply()
    assert "ADD LEARNER" in reply
