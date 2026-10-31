"""Unit tests for memory, STATE parsing, mastery and pedagogy: pure
functions, no database, no network. Spec: "Katlego memory + pedagogy spec
v0.1" (steps 1-3)."""

import random

import pytest

from app.tutor import mastery, memory, pedagogy
from app.tutor.state import parse_state, strip_state

LOS = {"ZA-MATH-G08-ALG-EQ-001", "ZA-MATH-G08-ALG-EQ-002"}
MISCS = {"SIGN_ERR", "ONE_SIDE_OP"}
STRATS = set(pedagogy.STRATEGIES)


def _parse(line):
    return parse_state(line, lo_codes=LOS, misconception_codes=MISCS, strategies=STRATS)


# ── STATE line ───────────────────────────────────────────────────────────────

def test_state_is_stripped_and_parsed():
    reply = ("Nice try! What do you get if you subtract 5 from both sides?\n"
             "<<STATE lo=ZA-MATH-G08-ALG-EQ-001 ev=attempt_partial misc=SIGN_ERR "
             "strat=SOCRATIC_QUESTIONING hint=1 step=2/3>>")
    clean, body = strip_state(reply)
    assert "STATE" not in clean and clean.endswith("both sides?")
    st = _parse(body)
    assert st == {"lo": "ZA-MATH-G08-ALG-EQ-001", "ev": "attempt_partial", "misc": "SIGN_ERR",
                  "strategy": "SOCRATIC_QUESTIONING", "hint": 1, "step": "2/3", "valid": True}


def test_unknown_values_are_dropped_never_stored():
    st = _parse(" lo=MADE-UP-CODE ev=genius misc=TYPO strat=VIBES hint=9 step=lots")
    assert st["lo"] is None and st["ev"] == "none" and st["misc"] is None
    assert st["strategy"] is None and st["hint"] == 3 and st["step"] is None
    assert st["valid"] is False


def test_missing_or_truncated_state_never_leaks():
    assert strip_state("Just a reply?") == ("Just a reply?", None)
    clean, body = strip_state("What next?\n<<STATE lo=ZA-MATH-G08-ALG-EQ-001 ev=attempt_c")
    assert clean == "What next?"
    assert _parse(body)["ev"] == "none"  # cut-off value is not trusted
    assert _parse(None) is None


# ── Mastery rule ─────────────────────────────────────────────────────────────

def test_three_correct_quiz_answers_follow_the_spec_example():
    m = mastery.MASTERY_START
    for _ in range(3):
        target, w = mastery.evidence_weight("quiz", "attempt_correct")
        m = mastery.update(m, target, w)
    assert m == pytest.approx(78.91, abs=0.01)  # 50 -> 62.5 -> 71.9 -> 78.9


def test_hints_reduce_credit_but_never_remove_it():
    w0 = mastery.evidence_weight("chat", "attempt_correct", 0)[1]
    w2 = mastery.evidence_weight("chat", "attempt_correct", 2)[1]
    w3 = mastery.evidence_weight("chat", "attempt_correct", 3)[1]
    assert w0 > w2 > w3 > 0


def test_no_evidence_means_no_event_and_scores_stay_in_range():
    assert mastery.evidence_weight("chat", "none") is None
    m = 99.0
    for _ in range(50):
        m = mastery.update(m, *mastery.evidence_weight("quiz", "attempt_correct"))
    assert m <= 100
    for _ in range(50):
        m = mastery.update(m, *mastery.evidence_weight("quiz", "attempt_wrong"))
    assert m >= 10


# ── Pedagogy rules ───────────────────────────────────────────────────────────

def _kw(**over):
    base = dict(score=55.0, current=None, fails_in_row=0, tried_on_problem=[],
                new_lo_this_session=False, misconception_repeated=False,
                review_due=False, has_open_problem=True, asked_answer_count=0,
                wrong_on_problem=0, stats={}, rng=random.Random(1))
    base.update(over)
    return base


def test_band_decides_the_starting_strategy():
    assert pedagogy.choose(**_kw(score=20))["strategy"] == "WORKED_EXAMPLE"
    assert pedagogy.choose(**_kw(score=55))["strategy"] == "SCAFFOLDED_EXAMPLE"
    assert pedagogy.choose(**_kw(score=90))["strategy"] == "SOCRATIC_QUESTIONING"


def test_new_objective_starts_with_prior_knowledge():
    d = pedagogy.choose(**_kw(new_lo_this_session=True, has_open_problem=False))
    assert d["strategy"] == "PRIOR_KNOWLEDGE_ACTIVATION"


def test_two_misses_switch_strategy_patience_is_not_repetition():
    d = pedagogy.choose(**_kw(current="SOCRATIC_QUESTIONING", fails_in_row=2,
                              tried_on_problem=["SOCRATIC_QUESTIONING"], wrong_on_problem=2))
    assert d["strategy"] == "SCAFFOLDED_EXAMPLE"  # no data -> next on the ladder
    assert d["hint"] == 2 and d["reveal"] is False


def test_bandit_prefers_what_worked_for_this_learner():
    stats = {"WORKED_EXAMPLE": (1, 0), "VISUAL_MODEL": (6, 6), "ANALOGY": (2, 0)}
    picks = {pedagogy.choose(**_kw(current="SCAFFOLDED_EXAMPLE", fails_in_row=2,
                                   tried_on_problem=["SOCRATIC_QUESTIONING", "SCAFFOLDED_EXAMPLE"],
                                   stats=stats, rng=random.Random(seed)))["strategy"]
             for seed in range(20)}
    assert picks == {"VISUAL_MODEL"}


def test_bounded_exploration_reveals_after_four_approaches():
    d = pedagogy.choose(**_kw(current="VISUAL_MODEL", fails_in_row=2,
                              tried_on_problem=list(pedagogy.LADDER[:4]), wrong_on_problem=3))
    assert d["strategy"] == "WORKED_EXAMPLE" and d["reveal"] and d.get("restart")


def test_repeated_misconception_is_remediated():
    d = pedagogy.choose(**_kw(misconception_repeated=True))
    assert d["strategy"] == "MISCONCEPTION_REMEDIATION"


def test_fallback_removes_the_one_turn_lag():
    d = pedagogy.with_fallback(_kw(current="SOCRATIC_QUESTIONING", fails_in_row=1,
                                   tried_on_problem=["SOCRATIC_QUESTIONING"], wrong_on_problem=1))
    assert d["strategy"] == "SOCRATIC_QUESTIONING" and d["fallback"] == "SCAFFOLDED_EXAMPLE"
    assert "ANOTHER wrong attempt" in pedagogy.decision_line(d)


# ── Memory window ────────────────────────────────────────────────────────────

def _state(ev, misc=None, step="1/3"):
    return {"lo": None, "ev": ev, "misc": misc, "strategy": "SOCRATIC_QUESTIONING",
            "hint": 0, "step": step, "valid": True}


def test_window_keeps_five_turns_and_consolidates_into_a_digest():
    mem = memory._new(7)
    topic = {"id": 1, "name": "Algebraic Equations"}
    flags = []
    evs = ["none", "attempt_wrong", "attempt_wrong", "attempt_correct", "none"]
    for i, ev in enumerate(evs):
        flags.append(memory.record_turn(mem, f"msg {i} solve 2x+5=17", f"Reply {i}. What next?",
                                        _state(ev, "SIGN_ERR" if ev == "attempt_wrong" else None),
                                        topic, "SOCRATIC_QUESTIONING"))
    assert flags == [False, False, False, False, True]
    line = memory.consolidate(mem)
    assert len(mem["turns"]) == memory.PROMPT_TURNS
    # The last 2 turns stay in the window; the first 3 roll into the digest.
    assert line == "Algebraic Equations: 0 right, 2 not yet; mistakes SIGN_ERR"


def test_topic_change_consolidates_and_resets_the_problem():
    mem = memory._new(7)
    memory.record_turn(mem, "how do I solve 2x+5=17", "What first?", _state("none"),
                       {"id": 1, "name": "Algebraic Equations"}, "SOCRATIC_QUESTIONING")
    memory.record_turn(mem, "what is the area of a circle of radius 3", "What formula?",
                       _state("none"), {"id": 14, "name": "Area and Perimeter"}, "SOCRATIC_QUESTIONING")
    assert mem["working"]["topic"] == "Area and Perimeter"
    assert mem["working"]["problem"].startswith("what is the area")
    assert mem["digest"] and mem.get("_persist")


def test_short_attempts_continue_the_problem():
    mem = memory._new(7)
    assert not memory.continues_problem(mem, "x = 4")  # nothing open yet
    mem["working"]["problem"] = "solve 2x + 5 = 17"
    assert memory.continues_problem(mem, "minus 5?")
    assert memory.continues_problem(mem, "x = 6")
    assert memory.continues_problem(mem, "just give me the answer")
    assert memory.continues_problem(mem, "because 3a and 5a are like terms so I add them")
    assert not memory.continues_problem(mem, "what about probability of rolling a dice")
    assert not memory.continues_problem(mem, "Solve 5x = 35")
    assert not memory.continues_problem(mem, "quiz me")


def test_reply_is_compressed_to_its_last_question():
    r = "Great start! You moved the 5 across. Now, what do you get if you divide both sides by 2?"
    assert memory.compress_reply(r) == "Now, what do you get if you divide both sides by 2?"


def test_a_failing_strategy_moves_toward_more_support_not_less():
    d = pedagogy.choose(**_kw(current="SCAFFOLDED_EXAMPLE", fails_in_row=2,
                              tried_on_problem=["SCAFFOLDED_EXAMPLE"], wrong_on_problem=2))
    assert d["strategy"] == "WORKED_EXAMPLE"


def test_a_second_request_for_the_answer_is_honoured_on_that_turn():
    assert memory.asks_for_answer("just give me the answer")
    assert memory.asks_for_answer("whats the answer")
    assert not memory.asks_for_answer("x = 4")
    d = pedagogy.choose(**_kw(asked_answer_count=2))
    assert d["reveal"] is True


def test_a_new_question_on_the_same_topic_starts_a_new_problem():
    mem = memory._new(7)
    t = {"id": 1, "name": "Algebraic Equations"}
    memory.record_turn(mem, "how do I solve 2x+5=17", "What first?", _state("none"), t, "SOCRATIC_QUESTIONING")
    memory.record_turn(mem, "x = 4", "Check it?", _state("attempt_wrong"), t, "SOCRATIC_QUESTIONING")
    assert mem["working"]["wrong_on_problem"] == 1
    memory.record_turn(mem, "and how do I solve 3x - 2 = 10", "What first?", _state("none"), t,
                       "SOCRATIC_QUESTIONING", new_problem=True)
    assert mem["working"]["problem"] == "and how do I solve 3x - 2 = 10"
    assert mem["working"]["wrong_on_problem"] == 0


def test_drifted_state_formats_never_reach_the_learner():
    cases = [
        "Try again?\n<<STATE lo=ZA-MATH-G08-ALG-EQ-001 ev=attempt_wrong strat=WORKED_EXAMPLE hint=1 step=1/3>>>",
        "Try again? <<STATE lo=<code> ev=none>> ",
        "Try again?\nSTATE: lo=ZA-MATH-G08-ALG-EQ-001 ev=none strat=WORKED_EXAMPLE",
        "Try again?\n<<STATE lo=ZA-MATH-G08-ALG-EQ-001 ev=att",
        "Try again? <STATE lo=ZA-MATH-G08-ALG-EQ-001 ev=none>\nKeep going!",
    ]
    for reply in cases:
        clean, _ = strip_state(reply)
        assert "STATE" not in clean and "<" not in clean and ">" not in clean, (reply, clean)
    # An ordinary sentence starting "State" is left alone.
    assert strip_state("State the rule first. What is it?")[0] == "State the rule first. What is it?"


def test_remediation_clears_the_misconception_trigger():
    mem = memory._new(7)
    t = {"id": 1, "name": "Integers"}
    memory.record_turn(mem, "what is -8 + 3", "Try?", _state("none"), t, "SOCRATIC_QUESTIONING", new_problem=True)
    memory.record_turn(mem, "11", "Hmm?", _state("attempt_wrong", "SIGN_ERR"), t, "SOCRATIC_QUESTIONING")
    memory.record_turn(mem, "-11", "Hmm?", _state("attempt_wrong", "SIGN_ERR"), t, "SOCRATIC_QUESTIONING")
    assert mem["working"]["misc_recent"] == ["SIGN_ERR", "SIGN_ERR"]
    memory.record_turn(mem, "-5", "Yes!", _state("attempt_correct"), t, "MISCONCEPTION_REMEDIATION")
    assert mem["working"]["misc_recent"] == []


def test_the_problem_opens_whatever_the_first_label_is():
    """Bench c04: "What is -8 + 3?" labelled asked_for_answer stored no
    problem, so the learner's "-5" retrieved exponents."""
    mem = memory._new(7)
    t = {"id": 1, "name": "Integers"}
    memory.record_turn(mem, "What is -8 + 3?", "Where do you start?", _state("asked_for_answer"), t,
                       "SOCRATIC_QUESTIONING", new_problem=True)
    assert mem["working"]["problem"] == "What is -8 + 3?"
    assert memory.continues_problem(mem, "-5")


def test_a_done_problem_stays_open_for_the_learners_echo():
    """Bench c10: "x = 2^5" marked done closed the problem, so "x = 32"
    retrieved compound angles."""
    mem = memory._new(7)
    t = {"id": 3, "name": "Logarithms"}
    memory.record_turn(mem, "solve log2 x = 5", "What does log mean?", _state("none"), t,
                       "SOCRATIC_QUESTIONING", new_problem=True)
    memory.record_turn(mem, "x = 2^5", "Yes! So x is?", _state("attempt_correct", step="done"), t,
                       "SOCRATIC_QUESTIONING")
    assert memory.continues_problem(mem, "x = 32")
    assert mem["working"]["wrong_on_problem"] == 0
    memory.record_turn(mem, "x = 32", "Well done!", _state("attempt_correct"), t, "SOCRATIC_QUESTIONING")
    assert not memory.has_open_problem(mem)


# ── Structured output (JSON state + reply) ───────────────────────────────────

from app.tutor.state import parse_turn, turn_schema  # noqa: E402


def test_json_turn_is_parsed_and_validated():
    raw = ('{"state": {"ev": "attempt_wrong", "lo": "ZA-MATH-G08-ALG-EQ-001", "misc": "SIGN_ERR", '
           '"strat": "SCAFFOLDED_EXAMPLE", "hint": "1", "step": "2/3"}, '
           '"reply": "Close!\\nWhat happens to the +5 when you subtract 5 from both sides?"}')
    reply, body, mode = parse_turn(raw)
    assert mode == "json" and reply.startswith("Close!\nWhat happens")
    st = _parse(body)
    assert st["valid"] and st["ev"] == "attempt_wrong" and st["hint"] == 1 and st["misc"] == "SIGN_ERR"


def test_unparseable_json_never_reaches_the_learner():
    reply, body, mode = parse_turn('{"state": {"ev": "none"}, "reply": "Nice one! What next?"  ')
    assert reply == "Nice one! What next?" and body is None and mode == "none"
    assert parse_turn('{"state": {"ev": "none", "re')[0] == ""
    assert parse_turn('```json\n{"state": {}, "reply": "Hi?"}\n```')[0] == "Hi?"


def test_state_line_still_works_as_the_fallback():
    reply, body, mode = parse_turn("Try again?\n<<STATE lo=none ev=none misc=none strat=ANALOGY hint=0 step=1/3>>")
    assert reply == "Try again?" and mode == "state_line" and _parse(body)["strategy"] == "ANALOGY"


def test_schema_enums_are_this_turns_candidates():
    s = turn_schema(["ZA-MATH-G08-ALG-EQ-001"], ["SIGN_ERR"], ["ANALOGY", "WORKED_EXAMPLE"])
    props = s["properties"]["state"]["properties"]
    assert props["lo"]["enum"] == ["ZA-MATH-G08-ALG-EQ-001", "none"]
    assert props["misc"]["enum"] == ["SIGN_ERR", "none"]
    assert list(s["properties"]) == ["state", "reply"]  # judge first, then write
    assert s["additionalProperties"] is False and s["properties"]["state"]["additionalProperties"] is False


def test_provider_refusing_the_schema_falls_back_to_prompt_json(monkeypatch):
    import asyncio

    from app.adapters import llm

    calls = []

    async def fake_complete(provider, tier, call, system, user, max_tokens, **kw):
        calls.append(kw.get("json_schema") is not None)
        if kw.get("json_schema"):
            raise RuntimeError("Error code: 400 - response_format json_schema is not supported")
        return '{"state": {"ev": "none", "lo": "none", "misc": "none", "strat": "ANALOGY", "hint": "0", "step": "1/3"}, "reply": "Hi?"}'

    monkeypatch.setattr(llm, "_provider", lambda tier: "openrouter")
    monkeypatch.setattr(llm, "_complete", fake_complete)
    d = {"strategy": "ANALOGY", "why": "x", "hint": 0, "reveal": False, "require_attempt": True}

    async def run():
        out = await llm.socratic_reply("hi there friend", [], 8, pedagogy=d, lo_candidates=[], misconceptions=[])
        return out, llm.last_output_mode.get()

    out, mode = asyncio.run(run())
    assert calls == [True, False] and mode == "json_prompt"
    assert parse_turn(out)[0] == "Hi?"
