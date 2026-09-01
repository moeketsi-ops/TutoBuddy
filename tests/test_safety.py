"""Safety filter: crisis disclosures reach the referral script, never a
maths prompt — before consent, before intent routing (blueprint §4.2)."""


def test_crisis_message_gets_referral_not_tutoring(onboarded_chat):
    onboarded_chat.send_text("I don't want to live anymore")
    reply = onboarded_chat.wait_for_reply()
    assert "Childline" in reply
    assert "116" in reply


def test_safety_runs_even_before_consent(chat):
    # Brand-new number, no consent yet — referral must still win.
    chat.send_text("my uncle abuses me at home")
    reply = chat.wait_for_reply()
    assert "Childline" in reply
    assert "POPIA" not in reply


def test_normal_maths_message_is_not_flagged(onboarded_chat):
    onboarded_chat.send_text("Solve 2x squared + 3x - 4 = 0")
    reply = onboarded_chat.wait_for_reply()
    assert "Childline" not in reply
