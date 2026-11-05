"""Prompt caching: cache fields from provider usage, prefix accounting, the
layered layout's order (stable first), and the evaluation arithmetic."""

from types import SimpleNamespace

from app.adapters import ledger, llm
from app.reports import cache_eval
from app.tutor import memory, prompts


def test_usage_reads_cached_and_written_tokens():
    u = SimpleNamespace(prompt_tokens=2000, completion_tokens=80, completion_tokens_details=None,
                        prompt_tokens_details=SimpleNamespace(cached_tokens=1536, model_extra={"cache_write_tokens": 0}),
                        model_extra={"cost": 0.0001})
    d = llm._usage_dict(u)
    assert d["cached_tokens"] == 1536 and d["cache_write_tokens"] == 0 and d["input_tokens"] == 2000
    a = SimpleNamespace(input_tokens=500, output_tokens=40, cache_read_input_tokens=1200,
                        cache_creation_input_tokens=300, model_extra={})
    d = llm._usage_dict(a)
    assert d["cached_tokens"] == 1200 and d["cache_write_tokens"] == 300


def test_prefix_account_measures_the_shared_start(monkeypatch):
    monkeypatch.setattr(llm, "_last_prompt", {})
    tok = ledger.current_learner.set(7)
    try:
        m1 = [{"role": "system", "content": "RULES " * 50}, {"role": "user", "content": "hi"}]
        first = llm._prefix_account("socratic_reply", m1)
        m2 = [m1[0], {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
              {"role": "user", "content": "next"}]
        second = llm._prefix_account("socratic_reply", m2)
    finally:
        ledger.current_learner.reset(tok)
    assert first["shared_chars"] == 0
    assert second["shared_chars"] >= len("RULES " * 50)
    assert second["shared_chars"] < second["prompt_chars"]


def test_cacheable_follows_provider_rules():
    assert cache_eval.cacheable(2000, 8000, 3000) == 0          # 750 shared tokens: under 1,024
    assert cache_eval.cacheable(2000, 8000, 5000) == 1152        # 1,250 -> 128-token steps
    assert cache_eval.cacheable(2000, 8000, None) == 0


def test_layered_system_holds_nothing_that_changes_each_turn():
    pedagogy = {"strategy": "SOCRATIC_QUESTIONING", "why": "default", "hint": 1, "level": "pictorial",
                "reveal": False, "require_attempt": True}
    a_sys, a_turn = prompts.socratic_layers(
        8, [], None, ["Integers", "Area and Perimeter"], None, profile_block="LEARNER PROFILE x",
        turn_memory="WORKING PROBLEM \"8 by 3\"", pedagogy=pedagogy)
    b_sys, b_turn = prompts.socratic_layers(
        8, [{"grade": 8, "subject": "Maths", "topic": "Area", "doc_type": "notes", "content": "A = l x b"}],
        None, ["Integers", "Area and Perimeter"], None, profile_block="LEARNER PROFILE x",
        turn_memory="WORKING PROBLEM \"9 m square\"", pedagogy={**pedagogy, "strategy": "WORKED_EXAMPLE"})
    assert a_sys == b_sys                      # identical system prompt: cacheable
    assert "WORKING PROBLEM" in a_turn and "WORKING PROBLEM" not in a_sys
    assert a_sys.index("GRADE FRAME") < a_sys.index("LEARNER PROFILE")
    assert a_turn != b_turn


def test_session_log_is_append_only_then_halves():
    mem = memory._new(1)
    memory.ensure_working(mem)
    for i in range(memory.SESSION_LOG_MAX):
        memory.record_turn(mem, f"msg {i}", f"reply {i}?", None, None, "SOCRATIC_QUESTIONING", new_problem=(i == 0))
    h = memory.history_messages(mem)
    assert len(h) == 2 * memory.SESSION_LOG_MAX and h[0]["content"] == "msg 0"
    memory.record_turn(mem, "one more", "ok?", None, None, "SOCRATIC_QUESTIONING", new_problem=False)
    assert len(mem["session_log"]) == memory.SESSION_LOG_MAX // 2 + 1


def test_profile_is_frozen_for_the_session():
    mem = memory._new(1, ["d1"])
    p1 = memory.profile_block(mem, name="Ntando", grade=8, lines=["WEAKER TOPICS Integers 20%"])
    p2 = memory.profile_block(mem, name="Ntando", grade=8, lines=["WEAKER TOPICS changed"])
    assert p1 == p2 and "Integers" in p1 and "EARLIER SESSIONS d1" in p1
