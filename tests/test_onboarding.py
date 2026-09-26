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


def test_delete_last_learner_drops_household_and_requires_reconsent(onboarded_chat):
    onboarded_chat.send_text("DELETE")
    reply = onboarded_chat.wait_for_reply()
    assert "erased" in reply.lower()
    # Nothing left in the DB for this phone (the POPIA "erase everything" promise).
    assert _rows_for_phone(onboarded_chat.phone) == {"account_channels": 0, "conversation_log": 0}
    onboarded_chat.send_text("hi again")
    assert "POPIA" in onboarded_chat.wait_for_reply()


def test_delete_with_sibling_keeps_household(onboarded_chat):
    onboarded_chat.send_text("ADD LEARNER")
    onboarded_chat.wait_for_reply()
    onboarded_chat.send_text("Naledi")
    onboarded_chat.wait_for_reply()
    onboarded_chat.send_text("9")
    onboarded_chat.wait_for_reply()
    onboarded_chat.send_text("DELETE")  # deletes Naledi (active), Thabo remains
    reply = onboarded_chat.wait_for_reply()
    assert "Switched to Thabo" in reply
    assert _rows_for_phone(onboarded_chat.phone)["account_channels"] == 1


def _rows_for_phone(phone: str) -> dict:
    import asyncio, os
    import asyncpg

    async def q():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            return {
                "account_channels": await conn.fetchval(
                    "SELECT count(*) FROM account_channels WHERE phone = $1", phone),
                "conversation_log": await conn.fetchval(
                    "SELECT count(*) FROM conversation_log WHERE phone = $1", phone),
            }
        finally:
            await conn.close()
    return asyncio.run(q())


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
