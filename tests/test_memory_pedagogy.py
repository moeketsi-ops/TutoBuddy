"""End to end: memory window, chat evidence -> mastery, pedagogy, token
ledger, sibling isolation and POPIA deletion (spec v0.1, steps 1-3).

Runs on the stub LLM: the stub emits a fixed STATE line (an attempt is
always 'partial', never a claimed correct answer), so these tests check the
plumbing, not tutoring quality. Needs seed.load_curriculum (Grade 8)."""

import asyncio
import json
import os

import asyncpg
import redis.asyncio as aioredis

from tests.conftest import AGREE

DB = os.environ.get("DATABASE_URL", "")
REDIS = os.environ.get("REDIS_URL", "")


def _q(sql, *args):
    async def run():
        conn = await asyncpg.connect(DB)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()
    return asyncio.run(run())


def _mem(learner_id):
    async def run():
        r = aioredis.from_url(REDIS, decode_responses=True)
        try:
            raw = await r.get(f"mem:{learner_id}")
            return json.loads(raw) if raw else None
        finally:
            await r.aclose()
    return asyncio.run(run())


def _learners(phone):
    return _q(
        "SELECT l.id, l.nickname FROM learners l JOIN account_channels c "
        "ON c.account_id = l.account_id WHERE c.phone = $1 ORDER BY l.id", phone)


def _onboard(chat, name="Lerato", grade="8"):
    for msg in ("hi", AGREE, name, grade):
        chat.send_text(msg)
        chat.wait_for_reply()


def test_follow_up_attempt_stays_on_the_problem_and_moves_mastery(chat):
    _onboard(chat)
    learner_id = _learners(chat.phone)[0]["id"]

    chat.send_text("How do I solve the equation 2x + 5 = 17?")
    first = chat.wait_for_reply()
    assert "<<STATE" not in first, first  # the hidden line never reaches a learner

    mem = _mem(learner_id)
    assert mem["working"]["problem"].startswith("How do I solve"), mem["working"]
    assert mem["working"]["topic"], mem["working"]

    chat.send_text("2x = 12")  # a short attempt: routed straight back to the tutor
    second = chat.wait_for_reply()
    assert "<<STATE" not in second

    mem = _mem(learner_id)
    assert len(mem["turns"]) == 2
    assert mem["turns"][1]["learner"] == "2x = 12"
    # code checks it (CPA spec): a valid step, not the answer -> 'partial'
    assert mem["working"]["wrong_on_problem"] == 1

    events = _q("SELECT source, evidence, weight, mastery_before, mastery_after "
                "FROM learner_events WHERE learner_id = $1", learner_id)
    assert [(e["source"], e["evidence"]) for e in events] == [("chat", "attempt_partial")]
    # partial = target 60 at chat weight 0.10: 50 -> 51 (a partial attempt
    # from a learner at 50 is slightly above their estimate)
    assert (float(events[0]["mastery_before"]), float(events[0]["mastery_after"])) == (50.0, 51.0)

    topic = _q("SELECT mastery_score FROM learner_topic_mastery WHERE learner_id = $1", learner_id)
    assert len(topic) == 1  # rolled up to the topic PROGRESS reads

    intents = _q("SELECT intent FROM conversation_log WHERE learner_id = $1 AND direction = 'outbound' "
                 "ORDER BY id DESC LIMIT 1", learner_id)
    assert intents[0]["intent"] == "homework"


def test_every_llm_call_is_in_the_ledger_with_state_validity(chat):
    _onboard(chat, "Ledger")
    learner_id = _learners(chat.phone)[0]["id"]
    chat.send_text("How do I solve the equation 3x - 4 = 11?")
    chat.wait_for_reply()
    rows = _q("SELECT call, provider, prompt_tokens, completion_tokens, estimated, strategy, "
              "state_valid, prompt_version, output_mode FROM llm_calls WHERE learner_id = $1", learner_id)
    socratic = [r for r in rows if r["call"] == "socratic_reply"]
    assert len(socratic) == 1, rows
    row = socratic[0]
    assert row["prompt_tokens"] > 100 and row["completion_tokens"] > 0
    assert row["strategy"] and row["state_valid"] is True
    assert row["prompt_version"] == "socratic-v4"
    assert row["output_mode"] == "json"  # structured output is the default
    if row["provider"] == "stub":
        assert row["estimated"] is True


def test_five_turns_write_a_digest_that_survives_the_session(chat):
    _onboard(chat, "Digest")
    learner_id = _learners(chat.phone)[0]["id"]
    chat.send_text("How do I solve the equation 2x + 5 = 17?")
    chat.wait_for_reply()
    # wrong, wrong, a step, wrong: x = 6 would be checked correct and close the problem
    for attempt in ("x = 11", "x = 4", "2x = 12", "x = 7"):
        chat.send_text(attempt)
        chat.wait_for_reply()
    mem = _mem(learner_id)
    assert len(mem["turns"]) == 2 and mem["digest"], mem
    saved = _q("SELECT memory_digest FROM learners WHERE id = $1", learner_id)[0]["memory_digest"]
    assert json.loads(saved) == mem["digest"]
    assert "not yet" in mem["digest"][-1]


def test_siblings_never_share_memory_and_delete_erases_it(chat):
    _onboard(chat, "Sipho")
    chat.send_text("How do I solve the equation 2x + 5 = 17?")
    chat.wait_for_reply()

    chat.send_text("ADD LEARNER")
    chat.wait_for_reply()  # consent is asked again for a sibling
    chat.send_text(AGREE)
    chat.wait_for_reply()
    chat.send_text("Naledi")
    chat.wait_for_reply()
    chat.send_text("8")
    chat.wait_for_reply()  # now Naledi is active
    chat.send_text("What is a common fraction and how do I simplify 6/8?")
    chat.wait_for_reply()

    sipho, naledi = _learners(chat.phone)
    m_sipho, m_naledi = _mem(sipho["id"]), _mem(naledi["id"])
    assert "2x + 5" in m_sipho["working"]["problem"]
    assert all("2x + 5" not in t["learner"] for t in m_naledi["turns"])

    chat.send_text("DELETE")  # deletes the active learner (Naledi) only
    chat.wait_for_reply()
    assert _mem(naledi["id"]) is None
    assert _q("SELECT 1 FROM learner_events WHERE learner_id = $1", naledi["id"]) == []
    assert _q("SELECT 1 FROM llm_calls WHERE learner_id = $1", naledi["id"]) == []
    assert _mem(sipho["id"]) is not None  # sibling untouched


def test_quiz_answers_use_the_same_evidence_stream(chat):
    _onboard(chat, "Quizzer")
    learner_id = _learners(chat.phone)[0]["id"]
    chat.send_text("quiz me")
    chat.wait_for_reply()
    chat.send_text("42")
    chat.wait_for_reply()
    events = _q("SELECT source, weight FROM learner_events WHERE learner_id = $1", learner_id)
    assert [e["source"] for e in events] == ["quiz"]
    assert float(events[0]["weight"]) == 0.25
